"""Shared orchestration helpers — thin wrappers to prevent duplication across server/MCP/CLI."""

from __future__ import annotations

import base64
import json as _json
import tempfile
from collections import Counter
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from src.config import settings
from src.generation import build_prompt, resize_screenshot
from src.intent import UserIntent, extract_intent
from src.models import (
    ContentBlock,
    ContextResponse,
    IntentInfo,
    ReferenceItem,
)
from src.primitives import (
    build_primitive_bundle,
    build_primitive_prompt_addendum,
)
from src.retrieval import RetrievalResult, cluster_diverse_retrieve, get_corpus_coverage, retrieve
from src.variation import (
    record_reference_usage,
    rerank_for_variation,
)


# ── Vision-based reference analysis ────────────────────────────────────────

_REFERENCE_ANALYSIS_PROMPT = """\
You are analyzing a screenshot of an award-winning website. Extract the EXACT visual parameters as structured data. Be extremely specific — no vague descriptions.

Return a JSON object with these fields:
{
  "background": "exact color (e.g. '#ffffff', 'cream #faf9f6', 'dark navy #0f172a')",
  "border_radius": "exact px value used on cards/containers (e.g. '0px', '4px', '8px', '16px')",
  "heading_font": "serif or sans-serif, weight (e.g. 'sans-serif, bold, condensed')",
  "heading_size_estimate": "approximate px size of largest heading (e.g. '72px', '96px')",
  "body_font": "serif or sans-serif (e.g. 'sans-serif, regular weight')",
  "color_palette": "list the 2-3 main colors and how they're used (e.g. 'charcoal #1a1a2e for text, teal #0d9488 on CTA button only, light gray #f1f5f9 for card backgrounds')",
  "color_count": "how many distinct accent colors (usually 1-2)",
  "layout_style": "describe the layout (e.g. 'asymmetric 60/40 split', 'centered single column', 'full-bleed image with overlay text')",
  "card_style": "how cards/containers look (e.g. '1px border #e2e8f0, no shadow, no radius', 'subtle shadow, 4px radius', 'no cards — just text sections')",
  "whitespace": "tight/moderate/generous spacing between sections",
  "overall_feel": "2-3 word description (e.g. 'sharp corporate minimal', 'editorial magazine', 'bold experimental')",
  "notable_techniques": "any special visual techniques (e.g. 'grain texture overlay', 'glassmorphism on navbar', 'oversized serif numbers as decoration')"
}

IMPORTANT: Be precise about border-radius. Most award-winning sites use SHARP corners (0-4px) or very subtle rounding (6-8px). If you see rounded-xl (16px+) corners, say so — but it's uncommon in high-quality design.

Return ONLY the JSON object, no markdown formatting."""


def analyze_reference_screenshot(image_bytes: bytes, domain: str) -> dict[str, str] | None:
    """Use Claude vision to extract structured design parameters from a reference screenshot.

    Returns a dict of CSS-level visual parameters, or None if analysis fails.
    """
    if not settings.anthropic_api_key:
        return None

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

        img_b64 = base64.b64encode(image_bytes).decode("utf-8")

        response = client.messages.create(
            model="claude-sonnet-4-6-20250627",
            max_tokens=600,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": img_b64,
                            },
                        },
                        {
                            "type": "text",
                            "text": _REFERENCE_ANALYSIS_PROMPT,
                        },
                    ],
                }
            ],
        )

        text = response.content[0].text.strip()
        # Strip markdown code fences if present
        if text.startswith("```"):
            text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.endswith("```"):
            text = text[:-3].strip()
        if text.startswith("json"):
            text = text[4:].strip()

        return _json.loads(text)
    except Exception:
        return None


def analyze_all_references(results: list[RetrievalResult]) -> list[dict[str, Any]]:
    """Analyze all reference screenshots with vision and return structured design specs.

    Returns a list of dicts, each containing the domain and extracted visual parameters.
    Falls back gracefully if the API key is missing or any analysis fails.
    """
    if not settings.anthropic_api_key:
        return []

    analyses: list[dict[str, Any]] = []
    for result in results:
        try:
            img_bytes = resize_screenshot(str(result.screenshot_path), max_width=1200)
            spec = analyze_reference_screenshot(img_bytes, result.domain)
            if spec:
                analyses.append({
                    "domain": result.domain,
                    "visual_spec": spec,
                })
        except Exception:
            continue

    return analyses


# ── DOM summary helpers ────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def _load_dom_summaries() -> dict[str, Any]:
    """Load dom_summaries.json (cached)."""
    path = settings.reference_data_dir / "dom_summaries.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return _json.load(f)


def _domain_to_dom_key(domain: str) -> str | None:
    """Find the DOM summary key for a given domain."""
    summaries = _load_dom_summaries()
    # dom_summaries keys are like "knock_app.html", "glideapps_com.html"
    slug = domain.replace(".", "_").replace("-", "_")
    for key in summaries:
        key_bare = key.replace(".html", "")
        if key_bare == slug or slug in key_bare or key_bare in slug:
            return key
    return None


def get_dom_summaries_for_domains(domains: list[str]) -> dict[str, dict]:
    """Return DOM summary data for a list of domains.

    Returns a dict mapping domain → {surface_techniques, detected_primitives, colors}.
    """
    summaries = _load_dom_summaries()
    result: dict[str, dict] = {}
    for domain in domains:
        key = _domain_to_dom_key(domain)
        if key and key in summaries:
            entry = summaries[key]
            result[domain] = {
                "surface_techniques": entry.get("surface_techniques", []),
                "detected_primitives": entry.get("detected_primitives", []),
                "colors": entry.get("colors", [])[:8],
            }
    return result


def build_reference_surface_analysis(
    domains: list[str],
) -> dict[str, Any]:
    """Synthesize aggregate surface technique analysis across references.

    Returns a dict with:
      - per_reference: DOM data per domain
      - technique_frequency: how many references use each surface technique
      - primitive_frequency: how many references use each detected primitive
      - design_vocabulary: natural-language summary of what the references actually do
    """
    per_ref = get_dom_summaries_for_domains(domains)
    if not per_ref:
        return {
            "per_reference": {},
            "technique_frequency": {},
            "primitive_frequency": {},
            "design_vocabulary": "No DOM summaries available for these references.",
        }

    technique_counts: Counter[str] = Counter()
    primitive_counts: Counter[str] = Counter()
    all_colors: list[str] = []

    for domain, data in per_ref.items():
        for t in data.get("surface_techniques", []):
            technique_counts[t] += 1
        for p in data.get("detected_primitives", []):
            primitive_counts[p] += 1
        all_colors.extend(data.get("colors", []))

    n = len(per_ref)
    # Build natural-language summary
    vocab_parts: list[str] = []
    for technique, count in technique_counts.most_common():
        pct = count / n
        if pct >= 0.6:
            vocab_parts.append(f"{technique} ({count}/{n} references — STRONGLY expected)")
        elif pct >= 0.4:
            vocab_parts.append(f"{technique} ({count}/{n} references — recommended)")

    # Filter primitives to interesting ones (not framework-level)
    skip_prims = {"tailwind", "bootstrap", "webflow", "wordpress", "shopify"}
    interesting_prims: list[str] = []
    for prim, count in primitive_counts.most_common():
        if prim not in skip_prims and count >= 2:
            interesting_prims.append(f"{prim} ({count}/{n})")

    design_vocabulary = (
        "Your references use these surface treatments — your output should match or exceed this level of visual richness:\n"
        + "\n".join(f"  - {v}" for v in vocab_parts)
        + ("\n\nDetected primitives in references (implement these for parity):\n"
           + "\n".join(f"  - {p}" for p in interesting_prims[:12])
           if interesting_prims else "")
    )

    return {
        "per_reference": per_ref,
        "technique_frequency": dict(technique_counts.most_common()),
        "primitive_frequency": dict(primitive_counts.most_common()),
        "design_vocabulary": design_vocabulary,
    }


# ── Context system prompt ───────────────────────────────────────────────────

CONTEXT_SYSTEM_PROMPT = """\
## YOUR DISPOSITION

You are a world-class creative director, not a template filler. Your reputation \
is on the line with every site. You don't care how long it takes — you care ONLY \
about the final product being extraordinary. Something a visitor screenshots and \
shares because it FEELS different from every other website they've seen.

You are building a UNIQUE site with its own visual identity and design language. \
Before you write a single line of code, you must INVENT what makes this site \
feel like no other. Not "another marketing page with a navbar and hero section." \
A site that feels like it was designed by a team that deeply understands the \
industry and crafted every detail to embody it.

## INVENT THE DESIGN LANGUAGE — DON'T FILL A TEMPLATE

The biggest failure mode is building "generic website with {company name} swapped \
in." The Apex/Orbital aerospace site has a mission status bar ("MISSION STATUS: \
NOMINAL"), vehicle class labels, launch designations — it feels like mission \
control software, not a marketing template. A law firm site might feel like a \
leather-bound legal brief. A biotech site might feel like a research paper.

Ask yourself: what UI would this company ACTUALLY use internally? What does their \
world look like? Then bring that visual language to the website. Every industry \
has its own native visual vocabulary:
- Aerospace → mission control displays, telemetry readouts, vehicle designations, \
  launch countdowns, status indicators, thin ruled lines, monospace data
- Finance → trading terminals, ticker displays, precise data tables, clean grids
- Architecture → blueprint aesthetics, section lines, scale indicators
- Medical → clinical precision, clean whites, structured data, imaging aesthetics
- Restaurant → menu typography, ingredient lists, editorial food photography
- Fashion → lookbook layouts, editorial spreads, runway aesthetics

Your navigation, your layout, your micro-copy, your section structure — ALL of \
it should feel native to the industry. Do NOT default to: logo-left, nav-center, \
CTA-right navbar on every site. INVENT navigation that serves THIS brand.

## CREATIVE FREEDOM IS MANDATORY

You are ENCOURAGED to invent custom visual techniques, micro-interactions, and \
layout ideas beyond the primitive palette. The primitives are your foundation — \
a starting toolkit — but the BEST sites go beyond them. If you have an idea \
for a custom CSS technique, an unusual layout, a creative use of typography, \
or an industry-native UI pattern that isn't in the primitives: DO IT.

What separates exceptional from generic:
- A hero that uses the FULL viewport width for typography, not a centered box
- Industry-specific metadata woven into the UI (dates, status codes, locations)
- Thin horizontal rules creating editorial structure and rhythm
- Photography that DOMINATES sections — 60-70% of visual area, not thumbnails
- Asymmetric image grids where one image is 3x the size of others
- Text that overlaps images, breaks grid boundaries, creates tension
- Custom section transitions — not just "white section, dark section, white section"

The site should look like it was art-directed, not assembled from components.

## HOW TO USE REFERENCE IMAGES

The reference screenshots show you VISUAL QUALITY LEVEL — the bar you must \
match or exceed. Extract:
- The COLOR FEELING (warm? cool? monochromatic? high contrast?)
- The TYPOGRAPHY CONFIDENCE (how big? what weight? serif or sans? viewport-spanning?)
- The SURFACE QUALITY (sharp or rounded? shadows or flat? borders or borderless?)
- The TEXTURE APPROACH (grain? photography? gradients? ruled lines? nothing?)
- The DENSITY (how much content per viewport? how big are the images?)
Then INVENT your own design language that matches the SAME QUALITY with \
INDUSTRY-NATIVE structure.

## SUB-AGENT QUALITY CONTROL

You MUST use sub-agents to keep yourself accountable. After building:
1. Spin up a REVIEW sub-agent that reads every page file and checks:
   - Does this feel like a CUSTOM site or a template with swapped content?
   - Is there industry-native visual language (not generic marketing patterns)?
   - Does the hero make you feel something, or is it just "big text + dark overlay"?
   - Are images PROMINENT — filling large areas, not thumbnails in card grids?
   - Would someone screenshot this and share it? What's the ONE moment that wows?
2. Call superpower_review_build to get AI vision-based section grades.
3. Fix everything flagged. Then review AGAIN. Keep iterating until it's right.
The sub-agent is fresh and not lazy — it will catch what you missed.

## MANDATORY PROCESS — EXECUTION PLAN (ExecPlan) THEN SUB-AGENT BUILD

You MUST follow this process. Do NOT start writing component code directly. \
The main conversation is for PLANNING. A sub-agent BUILDS.

PHASE 1 — GATHER CONTEXT AND DEFINE PERSONALITY (you do this):
  1. Call superpower_context → study reference_visual_specs + reference images
  2. BEFORE touching primitives, define the DESIGN PERSONALITY:
     - MOOD: What should this site make someone FEEL?
     - INDUSTRY LANGUAGE: What visual vocabulary is native to this industry? \
       What would their internal tools / documents / environment look like? \
       How can you bring that aesthetic to the website?
     - NAVIGATION CONCEPT: How should the nav work for THIS brand? A status \
       bar? A minimal wordmark with sparse links? A full-bleed menu? A sidebar? \
       DO NOT default to the standard "logo left, links center, CTA right" \
       pattern unless that genuinely serves the brand. Invent something.
     - ONE BOLD CHOICE: What's the ONE visual idea that makes this site \
       unmistakably different? (e.g. "viewport-width typography with faded \
       photography behind it" or "mission-control status displays woven into \
       every section" or "monochromatic with one violent accent color")
     - WHAT WE'RE NOT DOING: Name 3 common patterns we're explicitly avoiding.
     Write this personality down — it guides everything that follows.
  3. Call superpower_primitive_catalog → browse available primitives
  4. Call superpower_primitive_select → choose primitives that SERVE the \
     personality you defined. These are your foundation, not your ceiling.
  5. Call superpower_images 3+ times → get real Unsplash URLs

PHASE 2 — WRITE AN EXECPLAN (you do this):
  Write a detailed execution plan. It must be fully self-contained so a \
  sub-agent can build the entire site from it alone.

  The ExecPlan MUST include these sections:

  ## Purpose / Big Picture
  What the site is, who it's for, and the FEELING it should evoke. \
  Describe the DESIGN LANGUAGE you invented for this industry.

  ## Context and Orientation
  The reference_visual_specs and design parameters. npm install command \
  and import statements from the primitive addendum.

  ## Plan of Work — Section-by-Section Breakdown
  For EVERY section on EVERY page, describe in prose:
  - What content it contains (specific copy, not "a heading and some text")
  - What INDUSTRY-NATIVE visual treatment it uses
  - What layout it uses and WHY (not just "split 60/40" but the creative intent)
  - What background treatment and how it differs from neighboring sections
  - Which Unsplash image URL goes here and how prominent it is
  Be SPECIFIC and CREATIVE. Not "Hero section with heading" but \
  "Hero: full-viewport, company name in text-[12vw] spanning the entire \
  width with 10% opacity rocket photo behind it, thin ruled line beneath, \
  stats strip at the bottom showing 'VEHICLE CLASS: LEO · GTO · SSO' in \
  monospace tracking-widest — feels like mission control, not marketing."

  ## Concrete Steps
  Exact sequence of file operations. No rigid template — structure the \
  pages and components however serves the design best.

  ## Validation
  - npx next build succeeds with zero errors
  - Every section has framer-motion entrance animation
  - Real Unsplash URLs in every image slot (NO placeholders)
  - Multiple pages, each with substantial content
  - The site has a coherent design language that feels industry-native
  - Photography is PROMINENT — not thumbnails in card grids

PHASE 3 — SPAWN SUB-AGENT TO BUILD (you do this):
  Launch a sub-agent with the COMPLETE ExecPlan. The sub-agent builds the \
  entire site. Do not build it yourself.

PHASE 4 — REVIEW AND VERIFY (you do this after the sub-agent finishes):
  1. Read the built files. Does it match the creative vision?
  2. Run npx next build — must succeed.
  3. Start dev server and call superpower_check_layout on every page.
  4. Most importantly: does the site FEEL unique? Would you be proud of it?
  5. If any check fails — fix it or spawn another sub-agent to fix it.

## WHAT TO COPY FROM REFERENCES

The reference_visual_specs contain CSS parameters from reference screenshots:
- background color, border_radius, heading font/size, color palette, card style
- These set the QUALITY BAR — match or exceed their polish level

Study each reference image carefully. Extract:
  TYPE:       How big are headings? (Usually MASSIVE — 64px-96px+, often \
              viewport-spanning.) Mixed weights? Condensed or extended?
  COLOR:      How many colors? (Usually 1-2, used sparingly.) What are they?
  LAYOUT:     How much of the viewport does imagery fill? How asymmetric?
  SURFACES:   Cards? If so, how treated? (Thin 1px borders? No borders? \
              No cards at all — just editorial sections?)
  RHYTHM:     How do sections transition? Same bg? Alternating? Rules/lines?

## DESIGN FOR THIS SPECIFIC SITE

Primitives are your foundation, not your ceiling. Use them, but go beyond \
them when a custom technique better serves the design. Your goal is a site \
that looks art-directed, not assembled from a component library.

Use each background treatment ONCE per page maximum. Vary between: \
full-bleed photo, dark solid with grain, cream with prominent photography, \
white with editorial ruled lines, textured/patterned.

Every section should tell a STORY, not display data. If a section is just \
"heading + paragraph + card grid" — redesign it until it evokes feeling.

## EVERY SECTION MUST EARN ITS EXISTENCE

No section should be just "text on a flat background." Every section needs \
VISUAL RICHNESS — photography, typography at scale, texture, or pattern.

The measure is VISUAL DENSITY — every viewport the user scrolls through \
should reward them with something engaging. Dense visual information \
(photography, large typography, textures, asymmetric composition) is what \
makes sites feel premium. Dead empty space makes them feel unfinished.

## MATCH THE VISUAL LANGUAGE TO THE INDUSTRY

Different industries demand different visual languages: \
- Aerospace / defense / engineering → photography-dominant, technical metadata, \
  thin ruled lines, monospace labels, status indicators, precision aesthetics \
- Lifestyle / restaurant / fashion → full-bleed PHOTOGRAPHY with overlays, \
  editorial layouts, ingredient/detail typography \
- SaaS / developer tools / fintech → can use gradients and abstract textures, \
  but even these should feel specific, not generic \
- The ENTIRE site — navigation, section transitions, micro-copy, footer — \
  should feel native to the industry.

## VIEWPORT PRESENCE

Every full-viewport section (hero, CTA) must have content that is VERTICALLY \
CENTERED. Content pushed to the bottom of the viewport looks broken.

## IMAGES — USE url_full FOR ALL HERO AND FULL-BLEED SECTIONS

Use url_full (original resolution) for ANY image used as a section background \
or fill + object-cover. Use url for content images. url_small for avatars only.

## PRIMITIVES — USE THE PACKAGES

The primitive palette lists npm packages. Install and use them. If the palette \
says "@paper-design/shaders-react" and you write CSS @keyframes instead — use \
the package. The packages produce better results than hand-written CSS.

Beyond the packages, you are FREE to add custom CSS techniques, creative \
layouts, and industry-native UI patterns that aren't in the palette. The \
palette is your floor, not your ceiling.

## STRUCTURE

- The home page should have enough sections to tell the full story — typically \
  8+ visually distinct sections, each DIFFERENT from its neighbors.
- Multiple pages that make sense for THIS business. NOT a rigid template of \
  "home + pricing + about" — an aerospace company needs vehicles, missions, \
  facilities. A restaurant needs menu, reservations, story. A law firm needs \
  practice areas, cases, team. Choose pages that FIT.
- Real Unsplash images via superpower_images (call 3+ times). next/image for all.
- Framer-motion: useInView entrance on every section, useScroll parallax on 2+, \
  whileHover on all interactive elements.
- Real content: real names, real data, real detail. No lorem ipsum.
- No emojis.

## TECH

Next.js App Router, Tailwind CSS, framer-motion, @tabler/icons-react, \
next/font/google, next/image. No ShadCN. No Lucide. No component libraries.

IMPORTANT NODE.JS 25 FIX: framer-motion SSR will crash with \
"localStorage.getItem is not a function". Fix: set NODE_OPTIONS in package.json \
scripts: "dev": "NODE_OPTIONS='--localstorage-file=/tmp/nextls' next dev". \
Also add "use client" directive to ALL components that use framer-motion.

IMPORTANT TAILWIND v4 FIX: If Next.js scaffolds with Tailwind v4 (which uses \
@import "tailwindcss" instead of @tailwind directives), you MUST define all \
custom colors inside a @theme inline { } block in globals.css — NOT in :root. \
Example: @theme inline { --color-brand: oklch(0.55 0.25 250); --color-surface: \
#ffffff; } — then use "bg-brand" and "bg-surface" as utilities. Custom CSS \
variables in :root do NOT generate Tailwind utility classes in v4. If you use \
:root variables, your classes like "text-brand" will produce NO CSS output and \
the entire layout will break. Always verify with npx next build.

## VISUAL ANTI-PATTERNS TO AVOID

Do NOT use Tabler icons (or any icons) next to brand/company names in the \
navbar. Company names should be bold typography only — no icon logos.

Do NOT leave team member sections without real photographs. Call superpower_images \
for headshot photos and use them.

Do NOT create thin/lazy pages. Each page should have SUBSTANTIAL content.

Do NOT default to "logo left, nav links center, CTA button right" on every site. \
Invent navigation that serves the brand. A status bar, a minimal wordmark, an \
unconventional layout — anything that feels NATIVE to this industry.

Do NOT use dark overlays above 50% opacity on hero images — the image becomes \
invisible and you're left with "big text on dark rectangle." Let the photography \
show through. Use subtle overlays (20-35%) or NO overlay with text positioned \
in a safe area of the composition.
"""


def build_context_system_prompt(
    prompt: str,
    intent: UserIntent,
    results: list[RetrievalResult],
) -> tuple[str, dict]:
    """Compile request-specific system prompt with primitive orchestration addendum."""
    bundle = build_primitive_bundle(prompt, intent, results)
    addendum = build_primitive_prompt_addendum(bundle)
    return f"{CONTEXT_SYSTEM_PROMPT}\n\n{addendum}", bundle


def run_retrieval(
    prompt: str,
    page_type: str | None = None,
    industry: str | None = None,
    business_model: str | None = None,
    brand_tier: str | None = None,
    top_k: int = 5,
    no_vector: bool = False,
) -> tuple[UserIntent, list[RetrievalResult]]:
    """Extract intent and retrieve matching design references."""
    intent = extract_intent(
        prompt,
        page_type_override=page_type,
        industry_override=industry,
        business_model_override=business_model,
        brand_tier_override=brand_tier,
    )
    candidate_k = min(20, max(top_k, top_k * 4))
    results = retrieve(prompt, intent, top_k=candidate_k, no_vector=no_vector)

    # Variation pass: choose archetype, rerank references, then persist usage memory.
    if results:
        primitive_bundle = build_primitive_bundle(prompt, intent, results)
        archetype = primitive_bundle.get("variation_archetype", {})
        results = rerank_for_variation(results, archetype)
        results = results[:top_k]
        record_reference_usage(results)

    return intent, results


def run_diverse_retrieval(
    prompt: str,
    page_type: str | None = None,
    industry: str | None = None,
    business_model: str | None = None,
    brand_tier: str | None = None,
    top_k: int = 5,
) -> tuple[UserIntent, list[RetrievalResult]]:
    """Extract intent and retrieve cluster-diverse design references.

    Unlike run_retrieval (similarity-ranked), this picks one best representative
    per visual cluster — maximizing stylistic breadth over relevance score. Used
    by superpower_retrieve to ensure it returns genuinely different sites from
    what superpower_context already showed.
    """
    intent = extract_intent(
        prompt,
        page_type_override=page_type,
        industry_override=industry,
        business_model_override=business_model,
        brand_tier_override=brand_tier,
    )
    results = cluster_diverse_retrieve(intent, top_k=top_k)
    return intent, results


def intent_to_info(intent: UserIntent) -> IntentInfo:
    """Convert internal UserIntent dataclass to API-friendly IntentInfo."""
    return IntentInfo(
        page_type=intent.page_type,
        industry=intent.industry,
        business_model=intent.business_model,
        brand_tier=intent.brand_tier,
        industry_style_profile=intent.industry_style_profile,
        color_preference=intent.color_preference,
        style_keywords=list(intent.style_keywords),
    )


def result_to_reference_item(result: RetrievalResult) -> ReferenceItem:
    """Convert a RetrievalResult to an API-friendly ReferenceItem with base64 screenshot."""
    try:
        img_bytes = resize_screenshot(str(result.screenshot_path))
        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
    except Exception:
        img_b64 = ""

    return ReferenceItem(
        domain=result.domain,
        cluster_id=result.cluster_id,
        similarity=result.similarity,
        descriptor=result.descriptor,
        screenshot_base64=img_b64,
    )


def save_reference_images(results: list[RetrievalResult]) -> list[dict]:
    """Save reference screenshots to temp files and return metadata with paths.

    This is the key fix for MCP: instead of returning massive base64 strings
    in the tool response (which exceeds Claude Code's size limit), we save
    images to disk and return file paths that Claude Code can read natively
    with its Read tool (which supports vision).

    Each reference now includes DOM summary data (surface_techniques,
    detected_primitives, colors) when available.
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="superpower_refs_"))
    references = []

    # Pre-load DOM summaries for all domains
    domains = [r.domain for r in results]
    dom_data = get_dom_summaries_for_domains(domains)

    for i, result in enumerate(results, 1):
        try:
            img_bytes = resize_screenshot(str(result.screenshot_path), max_width=1200)
            img_path = tmp_dir / f"ref_{i}_{result.domain.replace('.', '_')}.jpg"
            img_path.write_bytes(img_bytes)

            desc = result.descriptor
            ref_entry: dict[str, Any] = {
                "reference_number": i,
                "domain": result.domain,
                "image_path": str(img_path),
                "similarity": round(result.similarity, 4),
                "visual_style": desc.get("visual_style", ""),
                "layout_pattern": desc.get("layout_pattern", ""),
                "typography_style": desc.get("typography_style", ""),
                "color_mode": desc.get("color_mode", ""),
                "industry": desc.get("industry", ""),
                "distinguishing_features": desc.get("distinguishing_features", ""),
            }

            # Include DOM summary if available
            if result.domain in dom_data:
                ref_entry["dom_analysis"] = dom_data[result.domain]

            references.append(ref_entry)
        except Exception:
            continue

    return references


def build_reference_images_for_remote(
    results: list[RetrievalResult],
) -> tuple[list[dict], list[bytes]]:
    """Build reference metadata and image bytes for remote MCP mode.

    Returns (references_meta, image_bytes_list). Unlike save_reference_images,
    this does not write to disk — image bytes are returned directly for embedding
    as MCP image content blocks.

    Each reference now includes DOM summary data when available.
    """
    references = []
    image_bytes_list = []

    # Pre-load DOM summaries for all domains
    domains = [r.domain for r in results]
    dom_data = get_dom_summaries_for_domains(domains)

    for i, result in enumerate(results, 1):
        try:
            img_bytes = resize_screenshot(str(result.screenshot_path), max_width=1200)
            desc = result.descriptor
            ref_entry: dict[str, Any] = {
                "reference_number": i,
                "domain": result.domain,
                "similarity": round(result.similarity, 4),
                "visual_style": desc.get("visual_style", ""),
                "layout_pattern": desc.get("layout_pattern", ""),
                "typography_style": desc.get("typography_style", ""),
                "color_mode": desc.get("color_mode", ""),
                "industry": desc.get("industry", ""),
                "distinguishing_features": desc.get("distinguishing_features", ""),
            }

            if result.domain in dom_data:
                ref_entry["dom_analysis"] = dom_data[result.domain]

            references.append(ref_entry)
            image_bytes_list.append(img_bytes)
        except Exception:
            continue

    return references, image_bytes_list


def build_context_payload(
    prompt: str,
    intent: UserIntent,
    results: list[RetrievalResult],
) -> ContextResponse:
    """Build the full context payload that any LLM caller can inject.

    Converts the Anthropic-specific message format from build_prompt()
    into a universal ContentBlock format.
    """
    messages = build_prompt(prompt, results)

    # Convert Anthropic message format to universal ContentBlock format
    converted_messages = []
    for msg in messages:
        converted_content = []
        for block in msg["content"]:
            if block["type"] == "text":
                converted_content.append(
                    ContentBlock(type="text", text=block["text"]).model_dump(exclude_none=True)
                )
            elif block["type"] == "image":
                source = block["source"]
                converted_content.append(
                    ContentBlock(
                        type="image",
                        media_type=source["media_type"],
                        data=source["data"],
                    ).model_dump(exclude_none=True)
                )
        converted_messages.append({"role": msg["role"], "content": converted_content})

    compiled_system_prompt, primitive_bundle = build_context_system_prompt(prompt, intent, results)

    return ContextResponse(
        system_prompt=compiled_system_prompt,
        messages=converted_messages,
        metadata={
            "intent": intent_to_info(intent).model_dump(),
            "num_references": len(results),
            "domains": [r.domain for r in results],
            "primitives": primitive_bundle,
        },
    )


def search_images(query: str, count: int = 10, orientation: str | None = None) -> list[dict]:
    """Search Unsplash for images and return URLs + metadata.

    Returns image URLs that can be used directly in <img> tags and next/image.
    Unsplash allows hotlinking via their CDN.
    """
    access_key = settings.unsplash_access_key
    if not access_key:
        # Fallback: return constructable Unsplash source URLs (no API key needed)
        # These use Unsplash's deprecated but still functional source redirect
        results = []
        terms = query.split(",") if "," in query else [query]
        for i, term in enumerate(terms[:count]):
            term = term.strip()
            w, h = (1200, 800) if orientation != "portrait" else (800, 1200)
            results.append({
                "url": f"https://images.unsplash.com/photo-{1550000000000 + i * 100000}?w={w}&h={h}&fit=crop&q=80",
                "search_url": f"https://unsplash.com/s/photos/{term.replace(' ', '-')}",
                "query": term,
                "width": w,
                "height": h,
                "description": f"Search Unsplash for '{term}' and pick a real photo URL",
                "note": "No UNSPLASH_ACCESS_KEY set. Visit search_url to find real image URLs manually, or set the key in .env for automatic results.",
            })
        return results

    params = {
        "query": query,
        "per_page": min(count, 30),
        "content_filter": "high",
    }
    if orientation:
        params["orientation"] = orientation

    resp = httpx.get(
        "https://api.unsplash.com/search/photos",
        params=params,
        headers={"Authorization": f"Client-ID {access_key}"},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()

    results = []
    for photo in data.get("results", []):
        urls = photo.get("urls", {})
        user = photo.get("user", {})
        results.append({
            "url": urls.get("regular", ""),  # 1080px wide, good for web
            "url_small": urls.get("small", ""),  # 400px wide, thumbnails
            "url_full": urls.get("full", ""),  # original resolution
            "width": photo.get("width", 0),
            "height": photo.get("height", 0),
            "description": photo.get("description") or photo.get("alt_description") or "",
            "photographer": user.get("name", ""),
            "photographer_url": user.get("links", {}).get("html", ""),
            "color": photo.get("color", ""),  # dominant color hex
            "unsplash_url": photo.get("links", {}).get("html", ""),
        })

    return results
