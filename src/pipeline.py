"""Shared orchestration helpers — thin wrappers to prevent duplication across server/MCP/CLI."""

from __future__ import annotations

import base64
import tempfile
from pathlib import Path

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

# ── Context system prompt ───────────────────────────────────────────────────

CONTEXT_SYSTEM_PROMPT = """\
You are a world-class frontend engineer and UI designer. You have been given \
a set of screenshot images from real, professionally designed and award-winning \
websites. These are your design references — they are your PRIMARY SOURCE OF \
VISUAL TRUTH. Everything you build MUST look like it came from one of these \
sites, not from a template or component library. Deviating from this is failure.

## NON-NEGOTIABLE REQUIREMENTS

These are not suggestions. Every single one of these MUST be present in your output:

1. MINIMUM 8 DISTINCT SECTIONS per page — hero, social proof, features (varied layouts), \
   testimonials, stats, process/how-it-works, gallery or visual showcase, CTA, footer. \
   Each section must be visually distinct from every other section.
2. REAL IMAGES EVERYWHERE — call superpower_images to get real Unsplash URLs. Every \
   section that can have an image MUST have one. No colored rectangles, no gradients \
   as image substitutes, no placeholder boxes. Real photographs only.
3. FRAMER-MOTION ANIMATIONS on every single element — entrance animations on scroll \
   (useInView), parallax effects (useScroll+useTransform), hover states, stagger \
   children. Every section animates. Every interactive element has a hover effect.
4. FULL MULTI-PAGE APP ROUTER STRUCTURE: app/page.tsx (home, 8+ sections), \
   app/about/page.tsx, app/services/page.tsx (or domain-relevant), shared layout.tsx \
   with Navbar and Footer. Use <Link href=...> not anchor tags.
5. USE THE PRIMITIVES FROM THE PALETTE — the primitive selections below are MANDATORY. \
   You MUST implement every listed primitive. Not optional, not "if it fits" — required.
6. REALISTIC CONTENT — real company names, real product descriptions, real pricing, \
   real testimonial quotes with full names and titles. Zero placeholder text.
7. PROPER CENTERING AND LAYOUT — content must be horizontally centered in the viewport, \
   use max-w-7xl mx-auto px-6 containers. No content should appear stuck to an edge \
   unless intentionally full-bleed.
8. NO EMOJIS — almost never use emojis anywhere in the UI. Professional websites do not \
   use emojis in headings, body copy, buttons, or labels. Only use an emoji if you have \
   a very specific, intentional reason and it would look genuinely wrong without one.

## Why these references matter

People cannot verbally communicate the precise spacing, color palette, typography \
hierarchy, shadow depths, border radii, gradient angles, or layout rhythm that \
separates a world-class website from a generic one. That gap is exactly what \
these references fill. Without them, you fall back to training data defaults — \
and those defaults produce generic, template-looking output. The references ARE \
the design specification. Treat them as binding.

NOTE: The reference screenshots often show the top/hero portion of each site. \
The full page continues below with more sections, content, and variation. \
Extrapolate: if the hero is this polished, the full page has MORE content, \
MORE sections, MORE visual variety. Your output must feel like a COMPLETE, \
DENSE, CONTENT-RICH production site.

## How to study the references

BEFORE writing any code, write a comment block naming specific elements you are \
taking from each reference. Format: "From ref 1: [specific layout pattern]. \
From ref 2: [specific color treatment]. From ref 3: [specific typography choice]." \
If you cannot name specifics, you have not studied the images — go back and look.

- WHAT MAKES IT FEEL EXPENSIVE? Identify the specific choices (spacing scale, \
  border treatment, type size, whitespace density, color restraint).
- NOTICE THE UNUSUAL CHOICES. Award-winning sites do NOT look like Bootstrap. \
  Find what makes each reference UNIQUE and reproduce that uniqueness.
- SPECIFIC DETAILS: border-radius values (often 0px or minimal), shadow styles \
  (often none or barely-there), typography scale (headings often text-7xl+), \
  color palette (often very limited — 1-2 colors used precisely).
- WHAT'S ABSENT: great design is as much about what's NOT there.

## BANNED PATTERNS — instant failure if used

These patterns make a site look AI-generated and fake. Using any of these without \
explicit reference support is a critical failure:

- GLOWING CTA BUTTONS with box-shadow glow or gradient backgrounds
- GRID/DOT/LINE PATTERN BACKGROUNDS
- FAKE CODE EDITOR or TERMINAL MOCKUPS
- IDENTICAL ROUNDED RECTANGLE CARD GRIDS (3-4 cards, same size, all rounded-xl)
- GRADIENT TEXT on headings (background-clip: text)
- FLOATING ORBS, BLURS, or BLOB DECORATIONS in backgrounds
- EXCESSIVE BORDER-RADIUS (rounded-2xl, rounded-3xl on everything)
- SHADCN/RADIX DEFAULT STYLING — component-library-looking output is failure
- LUCIDE/HEROICONS — use @tabler/icons-react exclusively
- "TRUSTED BY" LOGO BARS with fake logos
- BENTO GRIDS where every cell is a rounded rectangle with a gradient
- NEON/ELECTRIC COLOR ACCENTS on dark backgrounds (the default "dark SaaS" look)
- SPARSE PAGES with fewer than 8 sections
- REPEATING SECTION PATTERNS (hero → 3 features → pricing → footer, done)
- PLACEHOLDER IMAGES — every image must be a real Unsplash URL

## Design requirements

### Density and richness
- 8-15 distinct sections minimum. Dense, rich, full-page sites.
- Every section MUST look different from the last. Vary layouts, backgrounds, \
  typography scale, and content types aggressively. A grid section must be \
  followed by something completely different. Dark sections alternate with light. \
  Full-bleed alternates with contained. NEVER repeat a layout pattern.
- Real images in every section that can take one. Call superpower_images multiple \
  times with specific queries (hero backgrounds, team photos, product shots, \
  textures, industry imagery). Use url_full for hero backgrounds.
- Rich content: real stats (numbers), testimonial quotes (full name + title + \
  company), detailed feature breakdowns, comparison tables, process steps with \
  real descriptions.

### Animation (MANDATORY — not one section can be static)
- Import: `import { motion, useScroll, useTransform, useInView, AnimatePresence } \
  from "framer-motion"`
- EVERY section: wrap main content in `<motion.div>` with `useInView` trigger and \
  `variants` for stagger. No section can be static.
- Hero: entrance animation (fadeUp or blur-in) on every element, staggered.
- Parallax: at least 2 sections use `useScroll + useTransform` for parallax image \
  or text drift.
- Hover: every card, button, link, and interactive element has `whileHover`.
- Page transitions: `<AnimatePresence>` wrapping page content in layout.tsx.
- Target: feels like a Framer/Webflow site. Every scroll reveals something.

### Typography
- DRAMATIC scale: hero headings text-7xl to text-9xl on desktop (lg:text-8xl). \
  Never use text-3xl or text-4xl for a hero heading. This is the most common \
  mistake — go bigger.
- Weight contrast: font-light or font-thin for large display text, font-black for \
  emphasis words, font-medium for body.
- tracking-tighter or tracking-tight on large headings. tracking-wide or \
  tracking-widest on small uppercase labels.
- Mix serif and sans-serif. Use next/font/google. Options: Inter, Space Grotesk, \
  DM Sans, Instrument Serif, Playfair Display, Libre Baskerville.
- Break lines intentionally with <br/> for impact.

### Layout and composition
- COPY THE REFERENCES EXACTLY for layout DNA. Sharp corners in refs = sharp \
  corners in code. Asymmetric layout in refs = asymmetric in code.
- Mix asymmetric layouts with centered ones. Not everything is centered. Use \
  off-grid, overlapping, and full-bleed treatments.
- CSS Grid: span columns, vary cell sizes, overlap rows. Not uniform grids.
- Container rhythm: alternate max-w-7xl → full-bleed → max-w-5xl. This creates \
  visual interest across sections.
- Sections must have proper padding: py-24 or py-32 minimum (not py-12).

## MANDATORY Tech Stack

- Next.js 14+ App Router + Tailwind CSS
- `framer-motion` — ALL animations, no CSS animation fallbacks
- `@tabler/icons-react` — ALL icons
- `next/font/google` — typography
- `next/image` — all images (with real Unsplash URLs from superpower_images)
- ZERO component libraries: no ShadCN, no Radix, no Headless UI, no Lucide
- Build every element from scratch with Tailwind utilities
- Responsive: sm, md, lg, xl breakpoints on every layout

## Content standards

Real content everywhere:
- Company/product name: invent something real-sounding, not "Acme Corp"
- Features: specific, detailed descriptions (not "Feature 1 — Our feature does things")
- Pricing: real tiers with real prices ($29/mo, $79/mo, $199/mo) and real feature lists
- Testimonials: full name, job title, company, and a specific, detailed quote
- Stats: real numbers (10,000+ customers, $2.4M saved, 99.97% uptime)
- Never: Lorem ipsum, "Company Name", "Your Feature Here", placeholder text of any kind

## Image requirements

- Call superpower_images with specific, evocative queries:
  - Hero backgrounds: "dark abstract architectural texture", "aerial city night lights"
  - People: "professional smiling woman office", "diverse team meeting"
  - Product: industry-specific imagery
  - Sections: "minimal white desk workspace", "modern interior design"
- Use `url_full` for fullscreen hero backgrounds
- Use `url` (1080px) for cards and section images
- Every image in a next/image component with proper width, height, alt text
- Images MUST fill their containers properly: use `fill` prop + `object-cover` for \
  background images, explicit dimensions for content images

## Image performance (MANDATORY — slow images = failed site)

- HERO / above-the-fold images: add `priority` prop to `next/image` — this injects \
  a `<link rel="preload">` and disables lazy loading so the image loads immediately.
- ALL other images: add `sizes` prop matching the layout, e.g. \
  `sizes="(max-width: 768px) 100vw, (max-width: 1200px) 50vw, 33vw"` — this tells \
  the browser the correct render size so it fetches the smallest adequate variant.
- BLUR PLACEHOLDER on every image: add `placeholder="blur"` + a shimmer \
  `blurDataURL`. Use this exact shimmer helper once at the top of each file: \
  `const shimmer = (w: number, h: number) => \`<svg width="${w}" height="${h}" \
  xmlns="http://www.w3.org/2000/svg"><rect width="100%" height="100%" fill="#1a1a1a"/>\
  </svg>\`; const toBase64 = (str: string) => typeof window === 'undefined' ? \
  Buffer.from(str).toString('base64') : window.btoa(str);` \
  Then on each image: `placeholder="blur" blurDataURL={\`data:image/svg+xml;\
  base64,${toBase64(shimmer(700, 475))}\`}`
- This prevents layout shift and gives instant visual feedback instead of blank \
  white boxes while Unsplash CDN responds.

## Final check (run before output)

1. Does every section look visually different from the adjacent sections?
2. Does every element have a framer-motion entrance/hover animation?
3. Are there real Unsplash photos (not placeholders) in every image slot?
4. Are there 8+ sections on the home page?
5. Is there a multi-page structure (home + about + services/work)?
6. Are all listed primitives implemented?
7. Is all content realistic (no placeholder text)?
8. Is everything properly centered with max-w containers?
9. Do hero images have `priority` prop? Do all images have `sizes` and `placeholder="blur"` with a shimmer blurDataURL?
If any answer is NO — fix it before outputting.
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
    """
    tmp_dir = Path(tempfile.mkdtemp(prefix="superpower_refs_"))
    references = []

    for i, result in enumerate(results, 1):
        try:
            img_bytes = resize_screenshot(str(result.screenshot_path), max_width=1200)
            img_path = tmp_dir / f"ref_{i}_{result.domain.replace('.', '_')}.jpg"
            img_path.write_bytes(img_bytes)

            desc = result.descriptor
            references.append({
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
            })
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
    """
    references = []
    image_bytes_list = []

    for i, result in enumerate(results, 1):
        try:
            img_bytes = resize_screenshot(str(result.screenshot_path), max_width=1200)
            desc = result.descriptor
            references.append({
                "reference_number": i,
                "domain": result.domain,
                "similarity": round(result.similarity, 4),
                "visual_style": desc.get("visual_style", ""),
                "layout_pattern": desc.get("layout_pattern", ""),
                "typography_style": desc.get("typography_style", ""),
                "color_mode": desc.get("color_mode", ""),
                "industry": desc.get("industry", ""),
                "distinguishing_features": desc.get("distinguishing_features", ""),
            })
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
