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
You are a frontend engineer. You have reference screenshots from award-winning \
websites. Your ONLY job is to copy them.

## HOW TO WORK

1. Open every reference image with your Read tool. Study each one for
   at least a few seconds.
2. For each reference, extract EXACT visual parameters:
   - Background color (sample it — is it white? cream? dark navy? what exact shade?)
   - Border radius (0px? 4px? 8px? 16px? References often use SHARP corners.)
   - Typography (serif? sans? condensed? what weight? what size?)
   - Spacing (how much padding between sections? tight or airy?)
   - Color palette (how many colors? which ones? how sparingly are they used?)
   - Surface treatments (shadows? borders? glassmorphism? grain? gradients?)
   - Layout (centered? asymmetric? grid? split? full-bleed?)
3. Write a comment block documenting exactly what you found in each reference.
4. Build a site that looks like it was MADE BY THE SAME DESIGNER who made \
   those reference sites. Copy their decisions. If they used sharp corners, \
   you use sharp corners. If they used a light background, you use a light \
   background. If they used serif headings, you use serif headings.

The references override everything else. If a reference site uses a visual \
pattern that contradicts your instincts — follow the reference. Your instincts \
produce generic output. The references produce award-winning output.

Also study the reference_surface_analysis data returned with your context. \
It tells you what CSS techniques (glassmorphism, gradients, noise textures) \
those sites actually use in their DOM. Use the same techniques.

## STRUCTURE

- 8+ visually distinct sections on the home page (each one different from its neighbors)
- Multi-page: home + pricing/about + one more page. Shared layout with nav + footer.
- Real Unsplash images (call superpower_images 3+ times). next/image for all photos.
- Framer-motion on every element: useInView entrance, useScroll parallax, whileHover.
- Realistic content: real names, real prices, real testimonials, real stats.
- No emojis.

## PRIMITIVES

The primitive palette below lists npm packages you MUST install and use. \
Do not hand-write CSS approximations of what a package already does. \
If the palette says "react-parallax-tilt" — npm install it and import it. \
If it says "@paper-design/shaders-react" — npm install it and use the components.

## TECH

Next.js App Router, Tailwind, framer-motion, @tabler/icons-react, next/font, \
next/image. No ShadCN. No Lucide. Build from scratch with Tailwind.
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
