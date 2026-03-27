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
            model="claude-haiku-4-5-20251001",
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

You are building this site as if it's YOUR company — your reputation is on the \
line. You don't care how long it takes: 30 minutes, 2 hours, whatever it needs. \
You care ONLY about the final product being thorough, polished, and exceptional. \
What would normally take a team three weeks of iteration, you pack into one session.

You are building a UNIQUE site. Not "another B2B SaaS landing page." Every site \
has a different personality — a restaurant looks nothing like a dev tools company, \
which looks nothing like a law firm, which looks nothing like a fintech startup. \
Before you write a single line of code, you must define WHAT MAKES THIS SITE \
DIFFERENT from everything else you've ever built.

## HOW TO USE REFERENCE IMAGES

The reference screenshots show you VISUAL STYLE — colors, typography, textures, \
surface treatments. They do NOT show you layout blueprints. Do NOT copy the \
layout of the references (every reference shows a hero with left-text/right-widget \
— that doesn't mean YOUR site needs that). Instead, extract:
- The COLOR FEELING (warm? cool? monochromatic? high contrast?)
- The TYPOGRAPHY CONFIDENCE (how big? what weight? serif or sans?)
- The SURFACE QUALITY (sharp or rounded? shadows or flat? borders or borderless?)
- The TEXTURE APPROACH (grain? dot-grid? photography? gradients? nothing?)
Then INVENT your own layouts that express the SAME FEELING with DIFFERENT structure.

## SUB-AGENT QUALITY CONTROL

You MUST use sub-agents to keep yourself accountable. After building:
1. Spin up a REVIEW sub-agent that reads every page file and checks:
   - Is each section visually unique or are patterns repeating?
   - Are the chosen primitives actually used, not just installed?
   - Is there enough content on each page (not thin/stub pages)?
   - Does the site flow — do sections transition smoothly?
   - Would a non-technical person be impressed scrolling through this?
2. Call superpower_review_build to get AI vision-based section grades.
3. Fix everything flagged. Then review AGAIN. Keep iterating until it's right.
The sub-agent is fresh and not lazy — it will catch what you missed.

## MANDATORY PROCESS — EXECUTION PLAN (ExecPlan) THEN SUB-AGENT BUILD

You MUST follow this process. Do NOT start writing component code directly. \
The main conversation is for PLANNING. A sub-agent BUILDS.

PHASE 1 — GATHER CONTEXT AND DEFINE PERSONALITY (you do this):
  1. Call superpower_context → study reference_visual_specs + reference images
  2. BEFORE touching primitives, define the DESIGN PERSONALITY for this site:
     - MOOD: What should this site make someone FEEL? (calm authority? playful \
       energy? editorial sophistication? technical precision? warm trust?)
     - THEME: Light or dark? WHY? (Not all sites should be dark. Compliance \
       = trust = light. Dev tools = precision = maybe dark. Finance = \
       authority = light with selective dark sections. Decide intentionally.)
     - ONE BOLD CHOICE: What's the ONE visual idea that makes this site \
       unmistakably different from every other SaaS site? (e.g. "massive \
       outlined serif type as the only decorative element" or "full-bleed \
       photography, zero gradients" or "monochromatic teal with liquid glass")
     - WHAT WE'RE NOT DOING: Name 3 common patterns we're explicitly avoiding. \
       (e.g. "not doing dot-grid backgrounds, not doing dashboard mockup in \
       hero, not doing icon-card grids")
     Write this personality down — it guides everything that follows.
  3. Call superpower_primitive_catalog → browse available primitives
  4. Call superpower_primitive_select → choose 5-8 primitives that SERVE the \
     personality you defined. Not 18 "just in case" primitives — the focused \
     few that make this specific site's personality come alive. Different sites \
     should select DIFFERENT primitives. A compliance site might want serif \
     fonts + editorial layouts. A dev tools site might want monospace + bento \
     grids. A fintech site might want charts + liquid glass. THINK about it.
  5. Call superpower_images 3+ times → get real Unsplash URLs

PHASE 2 — WRITE AN EXECPLAN (you do this):
  Write a detailed execution plan following this format. The plan is a living \
  document — it must be fully self-contained so a novice agent can build the \
  entire site from it alone, with no memory of this conversation.

  The ExecPlan MUST include these sections:

  ## Purpose / Big Picture
  Explain what the site is, who it's for, and what someone sees when they \
  visit. State the user-visible behavior: "visiting localhost:3000 shows a \
  multi-page marketing site with 8+ sections, pricing page, about page..."

  ## Context and Orientation
  The reference_visual_specs extracted from award-winning screenshots. \
  Paste the EXACT design parameters: background colors, border-radius, \
  fonts, color palette, layout patterns. This is the design spec. \
  Also include the npm install command and import statements from the \
  primitive addendum.

  ## Plan of Work — Section-by-Section Breakdown
  For EVERY section on EVERY page, describe in prose:
  - What content it contains (specific copy, not "a heading and some text")
  - What layout it uses (split 60/40? centered? full-bleed? asymmetric grid?)
  - What background treatment (white? surface-1? dark? image? dot-grid?)
  - What primitives are used (Tilt card? CountUp? spotlight-hover?)
  - What animations (fade-up-stagger? parallax? blur-scale-in?)
  - Which Unsplash image URL goes here
  Be SPECIFIC. "Hero section with heading" is NOT a plan. \
  "Hero: 12-col grid, cols 1-7 has text-8xl heading in Space Grotesk \
  700 weight with the word 'faster' in accent color, cols 8-12 has a \
  product screenshot from [unsplash-url] in a border-card with 1px \
  border, spotlight-hover effect, bg-white, dot-grid overlay at 0.3 \
  opacity, fade-up-stagger entrance with 0.08s delay, useScroll parallax \
  on the image with range [-20px, 20px]" IS a plan.

  ## Concrete Steps
  The exact sequence of file operations:
  1. npx create-next-app OR reuse existing project
  2. npm install [full command from primitive addendum]
  3. Write next.config.ts (with images.remotePatterns for unsplash)
  4. Write globals.css (with exact design tokens)
  5. Write layout.tsx (with fonts, Navbar, Footer)
  6. Write each component file
  7. Write each page file
  8. Run npx next build to verify
  9. Run superpower_check_layout to verify visual quality

  ## Validation and Acceptance
  - npx next build succeeds with zero errors
  - Every section has framer-motion entrance animation
  - Every interactive element has whileHover
  - Real Unsplash URLs in every image slot
  - Multiple pages (home + pricing + about minimum)
  - Zero rounded-xl. Zero gradient text on full headings.
  - Colors match the reference_visual_specs exactly.
  - After building, run superpower_check_layout on localhost to verify \
    layout and visual richness.

  ## Progress
  - [ ] Project scaffolded and dependencies installed
  - [ ] Design tokens and globals.css written
  - [ ] Layout with Navbar + Footer written
  - [ ] Home page: hero section
  - [ ] Home page: remaining 7+ sections
  - [ ] Pricing page
  - [ ] About/third page
  - [ ] Build verification (next build)
  - [ ] Layout check (superpower_check_layout)

PHASE 3 — SPAWN SUB-AGENT TO BUILD (you do this):
  Launch a sub-agent (using the Agent tool) with the COMPLETE ExecPlan as \
  the prompt. The sub-agent builds the entire site. Do not build it yourself. \
  The sub-agent should update the Progress section as it works.

PHASE 4 — REVIEW AND VERIFY (you do this after the sub-agent finishes):
  1. Read the built files. Verify against the ExecPlan.
  2. Run npx next build — must succeed.
  3. Start dev server and call superpower_check_layout on every page.
  4. Check: are primitives imported? Colors correct? No rounded-xl?
  5. If any check fails — fix it or spawn another sub-agent to fix it.
  6. Do NOT finish until superpower_check_layout has been run successfully.

## WHAT TO COPY — USE THE reference_visual_specs

The reference_visual_specs field contains EXACT CSS parameters extracted from \
each reference screenshot by vision analysis. These are your design spec:
- background color → use that exact color
- border_radius → use that exact value (usually 0-4px, NOT rounded-xl)
- heading_font, heading_size_estimate → match the font style and scale
- color_palette → use those exact colors, that sparingly
- layout_style → copy that layout pattern
- card_style → copy that card treatment

Also open the reference images with your Read tool to see details the \
structured spec might miss. For each one, extract:

  BACKGROUND: What exact color? White (#fff)? Cream? Light gray? Dark navy? \
              Is it a photo? A gradient? What kind of gradient (not aurora blobs)?
  CORNERS:    What border-radius? Award-winning sites mostly use SHARP (0-4px) \
              or VERY subtle (6-8px). Almost never rounded-xl or rounded-2xl.
  TYPE:       Serif or sans? Condensed or extended? What weight? What size for \
              hero headings? (Usually MASSIVE — 64px-96px+, often with mixed weights \
              like thin+black in the same heading.)
  COLOR:      How many colors? (Usually 1-2, used VERY sparingly.) What are they? \
              Not purple+cyan+green — real sites use restraint.
  LAYOUT:     Centered? Asymmetric? Split? Full-bleed images? Magazine-style? \
              How much whitespace? (Award-winning sites are often either very \
              dense or use whitespace DRAMATICALLY — not the boring middle ground.)
  SURFACES:   How do cards look? (Thin 1px borders? No borders? Subtle shadows? \
              Frosted glass? NOT thick rounded borders with gradient backgrounds.)

Write a comment block documenting EVERY finding. Then build to match.

## DESIGN FOR THIS SPECIFIC SITE

Primitives are tools, not a checklist. Select 5-8 that serve THIS site's \
personality. A restaurant site needs different primitives than a compliance \
platform. A dev tools site needs different ones than a fashion brand. \
Think about what THIS company's personality calls for.

Use each background treatment ONCE per page maximum. If you've used dot-grid \
on one section, every other section needs a DIFFERENT treatment. This forces \
variety by construction.

The primitive registry has content_type_guidance — check it BEFORE designing \
each section. It tells you what the lazy AI default looks like and what \
award-winning sites do instead.

Every section should tell a STORY, not display data. Show transformation: \
before → after, problem → solution, complexity → simplicity. If a section \
is just "heading + paragraph + card grid" — redesign it until it evokes feeling.

## IMAGES — USE url_full FOR ALL HERO AND FULL-BLEED SECTIONS

When you get images from superpower_images, each image has url, url_full, url_small. \
Use url_full (original resolution) for ANY image that is fill + object-cover or \
used as a section background. Use url for content images in cards. url_small for \
avatars only. Using 1080px images on a 1440px+ viewport looks soft and cheap. \
EVERY hero, CTA, and full-bleed section MUST use url_full.

## PRIMITIVES — USE THE PACKAGES, NOT HAND-ROLLED CSS

The primitive palette below lists npm packages. npm install them. import them. \
Use them. If the palette says "@paper-design/shaders-react" and you write CSS \
@keyframes instead — that is a failure. The packages exist because they produce \
better results than hand-written CSS. Trust them.

You are NOT ALLOWED to use any visual technique that isn't from the primitive \
palette or directly copied from a reference image. No improvising. No "I'll add \
a nice gradient here." If it's not in the references and not in the primitives, \
don't use it.

## STRUCTURE

- 8+ visually distinct sections on the home page. Each DIFFERENT from neighbors.
- MINIMUM 3 PAGES — home + pricing + about (or integrations). A single-page site \
  is an automatic failure. Each page must be fully built with substantial content, \
  not a stub.
- Real Unsplash images via superpower_images (call 3+ times). next/image for all.
- Framer-motion: useInView entrance on every section, useScroll parallax on 2+, \
  whileHover on all interactive elements.
- Real content: real names, prices, testimonials (name + title + company), stats.
- No emojis. Pages scroll to top on navigation.

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

Do NOT create thin/lazy pages. Each page should have SUBSTANTIAL content — if a \
section looks like it could fit in a tweet, it needs 3x more content.
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
