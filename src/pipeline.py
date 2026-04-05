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


# ── Corpus-wide statistics (peer evidence) ────────────────────────────────

@lru_cache(maxsize=1)
def _compute_corpus_stats() -> dict[str, Any]:
    """Aggregate design technique usage across the entire DOM corpus.

    Returns top primitives and surface techniques with percentages.
    Cached — computed once per server lifetime.
    """
    summaries = _load_dom_summaries()
    if not summaries:
        return {"total": 0, "techniques": [], "primitives": []}

    total = len(summaries)
    prim_counts: Counter[str] = Counter()
    tech_counts: Counter[str] = Counter()

    # Framework-level signals to filter out (not design choices)
    skip = {"tailwind", "bootstrap", "webflow", "wordpress", "shopify",
            "squarespace", "wix", "elementor", "gatsby", "nuxt"}

    for data in summaries.values():
        for p in data.get("detected_primitives", []):
            if p not in skip:
                prim_counts[p] += 1
        for t in data.get("surface_techniques", []):
            tech_counts[t] += 1

    techniques = [
        {"name": name, "count": count, "pct": round(count / total * 100, 1)}
        for name, count in tech_counts.most_common(10)
        if count / total >= 0.01
    ]
    primitives = [
        {"name": name, "count": count, "pct": round(count / total * 100, 1)}
        for name, count in prim_counts.most_common(15)
        if count / total >= 0.05
    ]
    return {"total": total, "techniques": techniques, "primitives": primitives}


def format_corpus_peer_evidence() -> str:
    """Format corpus statistics as peer evidence for the disposition prompt.

    Returns a short section showing what award-winning sites actually use,
    framed as peer behavior rather than rules.
    """
    stats = _compute_corpus_stats()
    if not stats["total"]:
        return ""

    total = stats["total"]
    lines = [
        f"## WHAT {total:,} AWARD-WINNING SITES ACTUALLY USE",
        "",
        "This data comes from analyzing the DOM of every site in the reference corpus.",
        "These are the techniques that separate award-winning work from templates:",
        "",
    ]

    # Design techniques
    techniques = stats["techniques"]
    if techniques:
        lines.append("Surface techniques (% of award-winning sites that use them):")
        for t in techniques:
            lines.append(f"  - {t['name']}: {t['pct']}%")
        lines.append("")

    # Design-relevant primitives
    primitives = stats["primitives"]
    if primitives:
        lines.append("Packages and patterns used by top sites:")
        for p in primitives:
            lines.append(f"  - {p['name']}: {p['pct']}%")
        lines.append("")

    lines.append(
        "Sites that DON'T use these techniques are the ones that look generic. "
        "Layer 3-5 of these simultaneously for visual richness."
    )
    return "\n".join(lines)


# ── Industry vocabulary ────────────────────────────────────────────────────

@lru_cache(maxsize=1)
def load_industry_vocabulary() -> dict:
    """Load and cache industry-specific design vocabulary for creative provocation."""
    path = settings.reference_data_dir / "industry_vocabulary.json"
    with open(path) as f:
        return _json.load(f)


def get_industry_vocab(industry: str | None) -> dict:
    """Resolve an industry string to its vocabulary entry, following aliases."""
    if not industry:
        vocab_data = load_industry_vocabulary()
        return vocab_data.get("fallback", {})
    slug = industry.lower().replace(" ", "_").replace("-", "_")
    vocab_data = load_industry_vocabulary()
    industries = vocab_data.get("industries", {})
    aliases = vocab_data.get("industry_aliases", {})
    # Direct match
    if slug in industries:
        return industries[slug]
    # Alias match
    resolved = aliases.get(slug)
    if resolved and resolved in industries:
        return industries[resolved]
    # Fallback
    return vocab_data.get("fallback", {})


def generate_creative_provocations(
    industry: str | None,
    results: list[RetrievalResult],
) -> list[str]:
    """Generate industry-specific creative provocations for the design brief."""
    vocab = get_industry_vocab(industry)
    provocations = list(vocab.get("provocations", []))
    # Add reference-inspired provocations from distinguishing features
    for r in results[:3]:
        features = r.descriptor.get("distinguishing_features", "")
        if features and len(features) > 20:
            provocations.append(
                f"Reference {r.domain} uses: {features}. "
                "What elements from this approach could you reinterpret for your design?"
            )
    return provocations


def format_industry_context(industry: str | None) -> str:
    """Format industry vocabulary into a prompt section."""
    vocab = get_industry_vocab(industry)
    if not vocab:
        return ""
    parts: list[str] = []
    native = vocab.get("native_vocabulary", [])
    if native:
        parts.append(f"Native vocabulary for this industry: {', '.join(native[:12])}")
    concepts = vocab.get("section_concepts", {})
    if concepts:
        parts.append("\nSection concepts (use these as starting points, then go further):")
        for section_type, concept in concepts.items():
            parts.append(f"  {section_type}: {concept}")
    signals = vocab.get("premium_signals", [])
    if signals:
        parts.append(f"\nWhat communicates premium in this industry: {', '.join(signals)}")
    return "\n".join(parts)


# ── Context system prompt ───────────────────────────────────────────────────

CONTEXT_SYSTEM_PROMPT = """\
You design websites the way award-winning studios do — not by following \
templates, but by inventing visual languages rooted in each industry's \
native vocabulary.

## WHO YOU ARE

You are the creative director at a studio that wins Awwwards and FWA. \
Your work is recognized because every project feels designed FROM SCRATCH \
for that specific industry and brand. You never recycle layouts. You treat \
every section as an opportunity to make something someone would screenshot \
and share. Your instinct is always toward boldness — massive typography, \
dominant photography, surprising layouts, industry-native metaphors.

## HOW AWARD-WINNING SITES WORK

These patterns come from analyzing 1,662 award-winning reference sites:

- Every section has a CONCEPT — a visual metaphor rooted in the industry. \
  An aerospace features section looks like a flight manifest. A restaurant \
  menu uses rows with dividers like an actual printed menu. A fintech page \
  resembles a trading terminal. The metaphor makes the section unforgettable.

- Typography is the primary design tool. Headlines are massive and \
  viewport-spanning — text-[10vw] to text-[12vw], not text-5xl in a narrow \
  column. Mixed weights (thin + black) in the same heading. Display fonts \
  at 80-120px. Type does what decoration does on lesser sites.

- Photography dominates — 60-70% of visual area. Full-bleed backgrounds, \
  not thumbnails in cards. url_full for heroes/backgrounds, url for content, \
  url_small for avatars only. Dark overlays below 40% so images stay visible.

- Sharp, precise edges. Award-winning sites use 0-4px border radius. Sharp \
  corners communicate intentionality and craft. Rounded corners signal \
  auto-generated template work.

- Radical section variation. No two sections share a structural pattern. \
  Bento grid → full-bleed image with overlaid text → horizontal scroll → \
  split-screen narrative → editorial typography section. Each transition \
  surprises.

- Visual density in every viewport. No section is just text on a flat \
  background. Every scroll rewards the user with photography, texture, \
  pattern, bold typography, or interactive elements.

- Color restraint with intent. 2-3 complementary colors used consistently \
  throughout. When gradients are used, they are filtered or textured \
  (stepped-gradient-panels, noise overlay) — never raw CSS linear-gradient.

## THE MULTI-AGENT BUILD PROCESS

You are the orchestrator. Your job is creative direction and quality control. \
Sub-agents do the building. This distribution prevents laziness.

PHASE 1 — CONTEXT AND VISION:
  1. Call superpower_context to get references, visual specs, and industry \
     vocabulary. Study every reference image deeply.
  2. Call superpower_images 3+ times for real Unsplash photos (hero, team, \
     industry-specific imagery). Every image slot needs a real URL.

PHASE 2 — DESIGN BRIEF (the most important step):
  Write a section-by-section design brief. For each section describe: \
  the CONCEPT (visual metaphor), the LAYOUT, the INTERACTION, and the MOOD.
  Think in industry-native metaphors — "the features section is a flight \
  manifest with designation codes" not "features section with cards."
  Be wildly specific. Not "Hero with heading" but "Hero: company name in \
  text-[12vw] spanning full width, 10% opacity rocket photo behind it, thin \
  ruled line beneath, stats strip reading 'VEHICLE CLASS: LEO · GTO · SSO' \
  in monospace tracking-widest."
  Plan multiple pages (not home+pricing+about but pages that FIT the \
  industry — aerospace: vehicles, missions, facilities; restaurant: menu, \
  story, reservations). Home page needs 8-12+ substantial sections.

PHASE 3 — VALIDATE:
  Call superpower_design_review with your brief. A critic sub-agent reviews \
  it. If it doesn't pass — revise and re-submit. No building until the \
  brief is approved.

PHASE 4 — BUILD WITH SUB-AGENTS:
  Spawn section-builder sub-agents. Each gets 2-4 sections from the brief, \
  the relevant reference images, and the technical spec (packages, fonts, \
  colors). Their prompts are SHORT and focused — just the brief for their \
  sections plus the toolkit. Call superpower_section_context to get focused \
  context for each builder.

PHASE 5 — ASSEMBLE AND REVIEW:
  Stitch sections into pages. Handle routing, shared layout, ScrollToTop. \
  Call superpower_review_build on every page. Call superpower_check_layout. \
  Iterate until every page passes.

## STRUCTURAL RULES (layout bugs, not taste)

- Content in full-viewport sections MUST be vertically centered
- No two adjacent sections may share the same background approach
- Every multi-page site needs a ScrollToTop component (usePathname-based)
- Images need explicit height containers (next/image with fill + sized parent)
- Hero/CTA content must span viewport width, not sit in a narrow column

## TECH

Next.js App Router, Tailwind CSS v4, framer-motion, next/font/google, \
next/image. No ShadCN. No Lucide. No generic component libraries.

Tailwind v4: @theme inline { } for custom colors, NOT :root variables.
Node.js 25: NODE_OPTIONS='--localstorage-file=/tmp/nextls' in package.json scripts.
Framer-motion: "use client" on ALL components that use it.
ScrollToTop: usePathname() + window.scrollTo(0,0) on route change. \
If using Lenis: lenis.scrollTo(0, { immediate: true }) instead.
"""


def build_context_system_prompt(
    prompt: str,
    intent: UserIntent,
    results: list[RetrievalResult],
) -> tuple[str, dict]:
    """Compile request-specific system prompt with industry context and primitive toolkit."""
    bundle = build_primitive_bundle(prompt, intent, results)
    addendum = build_primitive_prompt_addendum(bundle)

    # Add industry-specific context
    industry_context = format_industry_context(intent.industry)
    provocations = generate_creative_provocations(intent.industry, results)

    parts = [CONTEXT_SYSTEM_PROMPT]

    # Corpus-wide peer evidence (what award-winning sites actually use)
    corpus_evidence = format_corpus_peer_evidence()
    if corpus_evidence:
        parts.append(corpus_evidence)

    if industry_context:
        parts.append(f"## INDUSTRY DESIGN VOCABULARY\n\n{industry_context}")

    if provocations:
        parts.append(
            "## CREATIVE PROVOCATIONS\n\n"
            "Use these as starting points — then go further:\n"
            + "\n".join(f"- {p}" for p in provocations)
        )

    parts.append(addendum)
    return "\n\n".join(parts), bundle


def build_assembler_prompt(
    pages: list[dict],
    font_spec: dict,
    color_palette: str,
    company_name: str = "",
) -> str:
    """Build a focused prompt for the assembler sub-agent.

    The assembler stitches approved section components into a working multi-page
    Next.js App Router application. It handles: page files, routing, shared layout,
    navbar/footer, ScrollToTop, and visual consistency.

    Each page dict has: name, route, sections (list of component names in order).
    """
    lines = [
        "You are the assembler. Section builders have already created the individual "
        "section components. Your job is to stitch them into a working multi-page "
        "Next.js App Router application.",
        "",
        "## PAGES TO ASSEMBLE",
        "",
    ]
    for page in pages:
        route = page.get("route", "/")
        name = page.get("name", "Page")
        sections = page.get("sections", [])
        lines.append(f"### {name} ({route})")
        lines.append(f"  Sections in order: {', '.join(sections)}")
        lines.append("")

    lines.extend([
        "## YOUR RESPONSIBILITIES",
        "",
        "1. **app/layout.tsx** — Root layout with:",
        f"   - Font imports (next/font/google) for {font_spec.get('display', 'display')} + {font_spec.get('body', 'body')} fonts",
        "   - Shared Navbar and Footer components",
        "   - ScrollToTop component (usePathname + window.scrollTo on route change)",
        "   - If using Lenis: initialize in layout, use lenis.scrollTo(0, {immediate: true}) in ScrollToTop",
        "",
        "2. **Page files** — Each route's page.tsx imports and renders its sections in order",
        "",
        "3. **Navbar** — INVENT navigation native to this brand. Not the default",
        "   'logo left, links center, CTA right' pattern unless it genuinely serves the brand.",
        f"   Company name '{company_name}' as bold text — no icon logo.",
        "",
        "4. **Footer** — Substantial, not an afterthought. Match the site's design language.",
        "",
        "5. **Visual consistency** — Ensure:",
        "   - Same font variables applied everywhere",
        f"   - Color palette: {color_palette}" if color_palette else "   - Consistent color palette from the design brief",
        "   - No two adjacent sections share the same background",
        "   - All section transitions feel intentional",
        "",
        "6. **globals.css** — Tailwind v4 setup:",
        "   - @import 'tailwindcss';",
        "   - @theme inline { } block for all custom colors (NOT :root)",
        "   - Any global styles (smooth scroll, selection color, etc.)",
        "",
        "## TECH REQUIREMENTS",
        "- Next.js App Router (app/ directory)",
        "- Tailwind CSS v4 (@theme inline, not :root)",
        "- 'use client' on all components with framer-motion or hooks",
        "- next/image for all images with explicit container heights",
        "- NODE_OPTIONS='--localstorage-file=/tmp/nextls' in package.json scripts",
        "- npx next build must succeed with zero errors",
        "",
        "## WHAT YOU DON'T DO",
        "- Don't redesign sections — they're already approved",
        "- Don't add new sections — the brief is final",
        "- Don't change section internals — only import and render them",
        "- Focus on: routing, layout, consistency, and making the app work",
    ])
    return "\n".join(lines)


def build_section_builder_prompt(
    section_briefs: list[dict],
    font_spec: dict,
    color_palette: str,
    primitive_toolkit: str,
) -> str:
    """Build a focused prompt for a section-builder sub-agent.

    Each section_brief dict has: concept, layout, interaction, mood, images.
    This prompt is intentionally SHORT (~80 lines) so the builder can attend to all of it.
    """
    lines = [
        "You are a section builder. Your ONLY job is to write incredible code for "
        "the sections described below. Each section must be worthy of an Awwwards "
        "feature — someone should want to screenshot it.",
        "",
        "## YOUR SECTIONS",
        "",
    ]
    for i, brief in enumerate(section_briefs, 1):
        lines.append(f"### Section {i}: {brief.get('name', f'Section {i}')}")
        lines.append(f"Concept: {brief.get('concept', 'N/A')}")
        lines.append(f"Layout: {brief.get('layout', 'N/A')}")
        lines.append(f"Interaction: {brief.get('interaction', 'N/A')}")
        lines.append(f"Mood: {brief.get('mood', 'N/A')}")
        images = brief.get("images", [])
        if images:
            lines.append(f"Images: {', '.join(images)}")
        lines.append("")

    if font_spec:
        display_font = font_spec.get("display", "Inter")
        body_font = font_spec.get("body", "Inter")
        lines.append(f"## FONTS: {display_font} (display) + {body_font} (body)")
        lines.append("")

    if color_palette:
        lines.append(f"## COLORS: {color_palette}")
        lines.append("")

    lines.extend([
        "## DESIGN STANDARDS",
        "- Sharp corners (0-4px radius). Rounded = template grade.",
        "- Typography is massive — viewport-spanning headlines, mixed weights.",
        "- Photography dominates — 60-70% of visual area in key sections.",
        "- Every section uses framer-motion (useInView entrance, whileHover on interactive).",
        "- Each section has a DIFFERENT layout approach from its neighbors.",
        "- Real content — specific names, numbers, dates. No lorem ipsum. No emojis.",
        "- 'use client' on all components using framer-motion.",
        "",
        "## TOOLKIT",
        primitive_toolkit,
    ])
    return "\n".join(lines)


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


def _cap_unsplash_width(url: str, max_w: int = 1920) -> str:
    """Append &w= to an Unsplash URL so the CDN delivers a pre-resized image.

    Without this, url_full returns the original (often 5000-9000px),
    and next/image must download the full file before resizing — very slow.
    """
    if not url or "unsplash.com" not in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}w={max_w}"


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
            "url_full": _cap_unsplash_width(urls.get("full", ""), 1920),  # capped at 1920px
            "width": photo.get("width", 0),
            "height": photo.get("height", 0),
            "description": photo.get("description") or photo.get("alt_description") or "",
            "photographer": user.get("name", ""),
            "photographer_url": user.get("links", {}).get("html", ""),
            "color": photo.get("color", ""),  # dominant color hex
            "unsplash_url": photo.get("links", {}).get("html", ""),
        })

    return results
