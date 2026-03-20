"""MCP tool server exposing the superpower pipeline for Claude Code.

Supports two transports:
  - stdio  (default, local):   python -m src.mcp_server
  - sse    (remote/hosted):    python -m src.mcp_server --sse
                               python -m src.mcp_server --sse --host 0.0.0.0 --port 8001
"""

from __future__ import annotations

import argparse
import os
from typing import Callable

import json

from mcp.server.fastmcp import FastMCP, Image
from mcp.server.transport_security import TransportSecuritySettings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.pipeline import (
    build_context_system_prompt,
    build_reference_images_for_remote,
    intent_to_info,
    run_diverse_retrieval,
    run_retrieval,
    save_reference_images,
    search_images,
)
from src.retrieval import get_corpus_coverage, load_industry_profiles
from src.layout_checker import check_layout, _is_local_url
from src.primitives import (
    build_manual_primitive_bundle,
    build_primitive_prompt_addendum,
    get_discovery_highlights,
    list_providers,
    load_primitive_registry,
)

_allowed_host = os.environ.get("MCP_ALLOWED_HOST")
_transport_security = (
    TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=[_allowed_host],
        allowed_origins=[f"https://{_allowed_host}"],
    )
    if _allowed_host
    else None
)

# When running as a remote HTTP/SSE server, images cannot be served via local file
# paths (the client has no access to the server's /tmp). Instead we embed images
# directly as MCP Image content blocks. Set SUPERPOWER_REMOTE=1 in the environment
# when deploying (fly.toml sets this automatically via the Dockerfile CMD).
_remote_mode: bool = os.environ.get("SUPERPOWER_REMOTE", "").lower() in ("1", "true", "yes")

mcp = FastMCP(
    "superpowering-agents",
    instructions="Design-reference-backed context injection for LLM code generation. "
    "When using superpower_context, you MUST carefully study each reference image "
    "returned before writing any code.",
    transport_security=_transport_security,
    stateless_http=True,
)


@mcp.tool(structured_output=False)
def superpower_context(
    prompt: str,
    page_type: str | None = None,
    industry: str | None = None,
    business_model: str | None = None,
    brand_tier: str | None = None,
    style_profile: str | None = None,
    top_k: int = 5,
    no_vector: bool = False,
    auto_primitives: bool = False,
    include_catalog: bool = False,
) -> list | dict:
    """Get design references + mandatory primitive palette for building world-class websites.

    Returns award-winning reference screenshots (study them deeply), metadata, and the
    full mandatory primitive catalog. You MUST follow this exact sequence — skipping
    any step is a failure:

    STEP 1 — STUDY EVERY REFERENCE IMAGE: Analyze each image carefully. Identify the
    exact spacing, typography scale, color palette, border treatment, layout rhythm,
    and what makes each site feel premium. Write a comment block naming specific visual
    elements you'll reproduce before writing any code.

    STEP 2 — BROWSE PRIMITIVES: Call superpower_primitive_catalog (no args) to see all
    ~60 available primitives. Study categories: layout (bento, masonry, sticky-narrative,
    horizontal-scroll), surface (glassmorphism, spotlight-card, elevated-card), text-effects
    (outlined-text, oversized-numerals, typewriter), background (mesh-gradient, noise-texture,
    aurora-gradient), buttons (cva variants), image-effects (grain, duotone).

    STEP 3 — SELECT PRIMITIVES: Call superpower_primitive_select with your chosen IDs.
    Pick from ALL categories. The primitives you select become MANDATORY — you must
    implement every single one you pick. Aim for 8+ primitives across 6+ categories.

    STEP 4 — GET REAL IMAGES: Call superpower_images MULTIPLE TIMES with specific queries:
    - Hero/section backgrounds (e.g., "dark abstract architectural texture")
    - People/team photos (e.g., "professional woman smiling office")
    - Industry imagery specific to the site's domain
    - Texture/ambient images for visual depth
    Every image slot in the site needs a real Unsplash URL. No placeholders.

    STEP 5 — BUILD THE SITE: Multi-page Next.js App Router with:
    - app/page.tsx: home page with 8+ visually distinct sections
    - app/about/page.tsx: full about page
    - app/services/page.tsx or domain-relevant third page
    - app/layout.tsx: shared Navbar + Footer, AnimatePresence
    - Every section uses framer-motion (useInView entrance, useScroll parallax, hover)
    - All images are real Unsplash URLs in next/image components
    - All content is realistic (real names, prices, stats, quotes)
    - Everything is properly centered with max-w-7xl mx-auto containers

    QUALITY MANDATE: This must look like a top design agency built it. 8+ sections,
    varied layouts, real images everywhere, framer-motion on every element, realistic
    content throughout. Generic template output is failure.
    """
    intent, results = run_retrieval(prompt, page_type, industry, business_model, brand_tier, top_k, no_vector)
    if style_profile:
        intent.industry_style_profile = style_profile
    corpus_coverage = get_corpus_coverage(intent)
    system_prompt = ""
    primitive_bundle = None
    if auto_primitives:
        system_prompt, primitive_bundle = build_context_system_prompt(prompt, intent, results)

    instructions = (
        "━━━ MANDATORY EXECUTION SEQUENCE — follow exactly, no shortcuts ━━━\n\n"
        "STEP 1 — STUDY EVERY REFERENCE IMAGE NOW:\n"
        "Before anything else, examine each reference image carefully. Identify: exact "
        "spacing rhythm, typography size scale (headings are often text-7xl+), color "
        "palette (usually very limited), border treatment (often sharp, 0px radius), "
        "layout structure, and what specific choices make each site feel premium. "
        "Write a comment block: 'From ref 1: [specific element]. From ref 2: [specific "
        "element].' Cannot write this = have not studied the images = go back and look.\n\n"
        "STEP 2 — BROWSE THEN SELECT PRIMITIVES (TWO CALLS REQUIRED):\n"
        "2a. Call superpower_primitive_catalog with no args to see all ~60 primitives.\n"
        "2b. Call superpower_primitive_select with chosen IDs from 6+ categories. "
        "Required categories: layout, surface, text-effects, background, animation/scroll, "
        "buttons. The primitives you select become NON-NEGOTIABLE — you MUST implement "
        "every single selected primitive. Pick boldly — unexpected combos = unique output.\n\n"
        "STEP 3 — GET REAL IMAGES (CALL MULTIPLE TIMES):\n"
        "Call superpower_images at least 3 times with different specific queries. "
        "Examples: 'dark cinematic architectural interior', 'professional team diverse "
        "office', 'abstract texture minimal dark'. Use url_full for hero backgrounds, "
        "url for section images. Every image slot needs a real URL — zero placeholders.\n\n"
        "STEP 4 — BUILD THE FULL MULTI-PAGE SITE:\n"
        "Files required: app/layout.tsx (Navbar + Footer + AnimatePresence), "
        "app/page.tsx (HOME — minimum 8 visually distinct sections), "
        "app/about/page.tsx (full about page), app/services/page.tsx or similar.\n\n"
        "SECTION REQUIREMENTS:\n"
        "• Every section must look DIFFERENT from adjacent sections (varied layout, "
        "background, typography scale, content type)\n"
        "• Section padding: py-24 or py-32 minimum\n"
        "• Content containers: max-w-7xl mx-auto px-6\n"
        "• Hero heading: lg:text-8xl or lg:text-9xl — never smaller than lg:text-6xl\n\n"
        "ANIMATION REQUIREMENTS (every element, no exceptions):\n"
        "• useInView + variants + staggered children on EVERY section\n"
        "• useScroll + useTransform parallax on at least 2 hero/image sections\n"
        "• whileHover on every card, button, link, and interactive element\n"
        "• AnimatePresence on route transitions in layout.tsx\n"
        "• Import: motion, useScroll, useTransform, useInView, AnimatePresence\n\n"
        "IMAGE REQUIREMENTS:\n"
        "• next/image for all images with real Unsplash URLs\n"
        "• Hero backgrounds: use fill + object-cover inside a relative container\n"
        "• Card images: explicit width/height with object-cover\n"
        "• No images cut off — set explicit heights on image containers\n\n"
        "CONTENT REQUIREMENTS:\n"
        "• Invent a real-sounding company name and product\n"
        "• 3+ testimonials with full name, job title, company, detailed quote\n"
        "• Stats section with real numbers (10,000+ users, $2.4M saved, 99.97% uptime)\n"
        "• Pricing with real tiers and real prices\n"
        "• Zero placeholder text anywhere\n\n"
        "FINAL CHECK before outputting:\n"
        "[ ] 8+ sections on home page, all visually distinct\n"
        "[ ] Every primitive from superpower_primitive_select is implemented\n"
        "[ ] Real Unsplash images in every image slot (no placeholders)\n"
        "[ ] framer-motion on every section and interactive element\n"
        "[ ] Multi-page structure (home + about + one more page)\n"
        "[ ] All content is realistic (no Lorem ipsum, no 'Company Name')\n"
        "[ ] Content is properly centered and padded\n"
        "If any box is unchecked — fix it before outputting."
    )

    catalog_payload = None
    if include_catalog or True:
        registry = load_primitive_registry()
        catalog_payload = {
            "version": registry.get("version"),
            "providers": registry.get("providers", []),
            "font_pairs": registry.get("font_pairs", []),
            "motion_primitives": registry.get("motion_primitives", []),
            "variation_archetypes": registry.get("variation_archetypes", []),
            "policy": registry.get("default_policy", {}),
        }

    if _remote_mode:
        references, image_bytes_list = build_reference_images_for_remote(results)
        payload = {
            "system_prompt": system_prompt,
            "intent": intent_to_info(intent).model_dump(),
            "corpus_coverage": corpus_coverage,
            "num_references": len(references),
            "references": references,
            "primitives": primitive_bundle,
            "instructions": instructions,
        }
        if catalog_payload is not None:
            payload["primitive_catalog"] = catalog_payload
        content: list = [json.dumps(payload)]
        for img_bytes in image_bytes_list:
            content.append(Image(data=img_bytes, format="jpeg"))
        return content

    references = save_reference_images(results)
    payload = {
        "system_prompt": system_prompt,
        "intent": intent_to_info(intent).model_dump(),
        "corpus_coverage": corpus_coverage,
        "num_references": len(references),
        "references": references,
        "primitives": primitive_bundle,
        "instructions": instructions,
    }
    if catalog_payload is not None:
        payload["primitive_catalog"] = catalog_payload
    return payload


@mcp.tool(structured_output=False)
def superpower_retrieve(
    prompt: str,
    page_type: str | None = None,
    industry: str | None = None,
    business_model: str | None = None,
    brand_tier: str | None = None,
    style_profile: str | None = None,
    top_k: int = 5,
) -> list | dict:
    """Retrieve a cluster-diverse set of design references — different from superpower_context.

    Unlike superpower_context (which returns the most similar references), this tool
    picks one high-quality representative from each visual cluster in the corpus.
    The result spans different visual neighborhoods — maximizing stylistic breadth.

    Use this when you want references that are visually diverse rather than
    references that are all similar to the prompt. Good for: discovering unexpected
    directions, breaking out of a style rut, or getting a broader design vocabulary.

    Also reports corpus_coverage so you know if the industry you requested actually
    has matching sites in the database (or if the results are style-matched fallbacks).
    """
    intent, results = run_diverse_retrieval(prompt, page_type, industry, business_model, brand_tier, top_k)
    if style_profile:
        intent.industry_style_profile = style_profile
    corpus_coverage = get_corpus_coverage(intent)

    if _remote_mode:
        references, image_bytes_list = build_reference_images_for_remote(results)
        payload = {
            "intent": intent_to_info(intent).model_dump(),
            "corpus_coverage": corpus_coverage,
            "retrieval_strategy": "cluster-diverse (one representative per visual cluster, sorted by quality)",
            "references": references,
            "instructions": (
                "Study each reference image carefully to extract visual patterns. "
                "These references were selected for maximum stylistic diversity — "
                "they span different visual neighborhoods rather than clustering "
                "around the prompt. Use them to broaden your design vocabulary."
            ),
        }
        content: list = [json.dumps(payload)]
        for img_bytes in image_bytes_list:
            content.append(Image(data=img_bytes, format="jpeg"))
        return content

    references = save_reference_images(results)
    return {
        "intent": intent_to_info(intent).model_dump(),
        "corpus_coverage": corpus_coverage,
        "retrieval_strategy": "cluster-diverse (one representative per visual cluster, sorted by quality)",
        "references": references,
        "instructions": (
            "Use your Read tool to open each image_path to see the design references. "
            "These references were selected for maximum stylistic diversity — "
            "they span different visual neighborhoods rather than clustering "
            "around the prompt. Use them to broaden your design vocabulary."
        ),
    }


@mcp.tool()
def superpower_primitives(
    prompt: str,
    page_type: str | None = None,
    industry: str | None = None,
    top_k: int = 5,
    no_vector: bool = False,
) -> dict:
    """Return the task-specific primitive bundle and compiled prompt addendum.

    Use this for debugging/tuning the primitive orchestration layer without
    generating full code.
    """
    intent, results = run_retrieval(prompt, page_type, industry, None, None, top_k, no_vector)
    system_prompt, primitive_bundle = build_context_system_prompt(prompt, intent, results)

    return {
        "intent": intent_to_info(intent).model_dump(),
        "num_references": len(results),
        "domains": [r.domain for r in results],
        "primitives": primitive_bundle,
        "system_prompt": system_prompt,
    }


@mcp.tool()
def superpower_primitive_catalog(category: str | None = None) -> dict:
    """Expose primitive catalog entries for client-side LLM selection.

    IMPORTANT: Read discovery_spotlight FIRST before browsing the full provider list.
    These are the primitives most developers never reach for but that produce the
    biggest visible differentiation from generic output. If you skip discovery_spotlight
    and only use animation/icons/forms (your defaults), the output will look like
    every other AI-generated site.

    After reviewing discovery_spotlight, browse all_providers for the full selection.
    Then call superpower_primitive_select with your chosen IDs.
    """
    registry = load_primitive_registry()
    discovery = get_discovery_highlights(registry) if not category else []
    return {
        "version": registry.get("version"),
        "category": category,
        "discovery_spotlight": discovery,
        "discovery_note": (
            "These providers are from categories most developers skip. "
            "Pick at least 2-3 from discovery_spotlight alongside your standard choices. "
            "They are what separate template-looking output from custom-feeling output."
        ) if discovery else None,
        "providers": list_providers(category),
        "font_pairs": registry.get("font_pairs", []),
        "motion_primitives": registry.get("motion_primitives", []),
        "variation_archetypes": registry.get("variation_archetypes", []),
        "policy": registry.get("default_policy", {}),
    }


@mcp.tool()
def superpower_primitive_select(
    provider_ids: list[str],
    font_pair_id: str | None = None,
    motion_ids: list[str] | None = None,
    archetype_id: str | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Build a primitive bundle from explicit primitive IDs chosen by the client LLM."""
    bundle = build_manual_primitive_bundle(
        provider_ids=provider_ids,
        font_pair_id=font_pair_id,
        motion_ids=motion_ids,
        archetype_id=archetype_id,
        tags=tags,
    )
    addendum = build_primitive_prompt_addendum(bundle)
    return {
        "primitives": bundle,
        "prompt_addendum": addendum,
        "selected_provider_ids": provider_ids,
        "selected_motion_ids": motion_ids or [],
        "selected_font_pair_id": font_pair_id,
        "selected_archetype_id": archetype_id,
    }


@mcp.tool()
def superpower_industry_profiles(industry: str | None = None) -> dict:
    """Return industry × style archetypes for deliberate design reference selection.

    Each archetype (e.g. "fintech_dark_minimal", "health_light_clean") is a named
    pattern capturing how companies in a given industry typically present themselves
    visually — combining industry, color mode, and visual style signals.

    WORKFLOW:
    1. Call this tool (optionally filtered by industry) to browse available archetypes.
    2. Pick the archetype key that best matches what you're building.
    3. Pass that key as style_profile= when calling superpower_context or superpower_retrieve.
       This activates composite scoring that boosts references matching both the industry
       AND the visual style of the archetype — much more precise than industry alone.

    Example:
      superpower_industry_profiles(industry="fintech")
      → returns archetypes: fintech_dark_minimal, fintech_light_clean
      → user picks "fintech_dark_minimal"
      → superpower_context(prompt=..., style_profile="fintech_dark_minimal")
      → retrieval now scores candidates on industry + dark + minimal style simultaneously

    Args:
        industry: Optional filter to show only archetypes matching this industry.
                  If omitted, returns all archetypes.
    """
    profiles = load_industry_profiles()
    if not profiles:
        return {
            "note": "industry_style_profiles.json not found. Run 06_build_industry_profiles.py in web-reference-corpus.",
            "profiles": {},
        }

    profile_defs = profiles.get("profiles", {})
    groups = profiles.get("industry_groups", {})

    # Filter by industry if requested
    if industry:
        profile_defs = {
            key: p for key, p in profile_defs.items()
            if industry in p.get("industries", [])
            or any(
                industry in members
                for grp_members in groups.values()
                for grp_ind in [industry]
                if industry in grp_members and key in profile_defs
            )
        }

    # Return a clean summary (omit heavy fields like example_domains for brevity)
    summaries = {}
    for key, p in profile_defs.items():
        summaries[key] = {
            "key": key,
            "industries": p.get("industries", []),
            "color_modes": p.get("color_modes", []),
            "typical_visual_styles": p.get("visual_styles", []),
            "description": p.get("description", ""),
            "cluster_count": p.get("cluster_count", 0),
            "avg_quality": p.get("avg_quality"),
            "example_domains": p.get("example_domains", [])[:5],
        }

    return {
        "total_archetypes": len(summaries),
        "industry_filter": industry,
        "industry_groups": groups,
        "archetypes": summaries,
        "usage": (
            "Pass the archetype key as style_profile= in superpower_context or "
            "superpower_retrieve to activate combined industry+style scoring."
        ),
    }


@mcp.tool()
def superpower_generate(
    prompt: str,
    page_type: str | None = None,
    industry: str | None = None,
    top_k: int = 5,
    no_vector: bool = False,
) -> dict:
    """Generate a Next.js/Tailwind TSX component using design references.

    Runs the full pipeline: intent extraction, reference retrieval,
    and Claude-powered code generation using reference screenshots
    as visual context. Returns the generated TSX code and references used.
    """
    from src.generation import generate_code

    intent, results = run_retrieval(prompt, page_type, industry, None, None, top_k, no_vector)
    system_prompt, _ = build_context_system_prompt(prompt, intent, results)
    code = generate_code(prompt, results, system_prompt=system_prompt)
    references = save_reference_images(results)

    return {
        "intent": intent_to_info(intent).model_dump(),
        "code": code,
        "references": references,
    }


@mcp.tool()
def superpower_images(
    query: str,
    count: int = 8,
    orientation: str | None = None,
) -> dict:
    """Search for real Unsplash photographs for website designs. CALL THIS MULTIPLE TIMES.

    Returns real, production-ready image URLs. Unsplash allows hotlinking — URLs work
    in production next/image components directly.

    YOU MUST call this tool for EVERY image slot in the site. No placeholder images,
    no colored rectangles, no gradient substitutes. Every image must be a real photo.

    Call this tool multiple times with different specific queries:
    - Hero background: "dark cinematic architectural interior texture"
    - Team/people: "professional woman smiling workspace modern"
    - Abstract/ambient: "minimal abstract dark concrete texture"
    - Industry-specific: tailor to the site's domain (tech, fashion, food, etc.)
    - Product lifestyle: "luxury product flat lay minimal"

    Image usage in code:
    - url_full → hero section backgrounds (fill + object-cover, min-h-screen container)
    - url → standard content images (explicit width/height, object-cover)
    - url_small → avatar/thumbnail images
    - ALWAYS use next/image with proper dimensions — never <img> tags
    - Give image containers explicit heights (h-64, h-96, etc.) so images don't collapse

    Query tips for quality results:
    - Be evocative and specific: "dark moody nordic interior" not "interior"
    - Use lighting descriptors: "golden hour", "dramatic light", "soft diffuse"
    - Use mood words: "cinematic", "minimal", "editorial", "luxury"

    Args:
        query: Specific, evocative search terms for the image needed
        count: Number of images to return (default 8, max 30)
        orientation: "landscape" for hero/wide images, "portrait" for cards, "squarish" for avatars
    """
    results = search_images(query, count=count, orientation=orientation)
    return {
        "images": results,
        "usage_note": (
            "url_full = full resolution for hero backgrounds (use with fill+object-cover). "
            "url = 1080px for content images (use with explicit width/height). "
            "url_small = 400px for avatars/thumbnails. "
            "Always use next/image. Always give containers explicit heights."
        ),
    }


@mcp.tool(structured_output=False)
def superpower_check_layout(
    url: str,
    viewport_width: int = 1440,
    mobile: bool = False,
) -> list | dict:
    """Detect visual layout issues on a rendered page. Run this after building a site.

    Launches a headless Chromium browser, navigates to the URL, injects a DOM
    inspection script, and finds real rendering problems: overlapping elements,
    content overflow, collapsed containers, and off-viewport content.

    Each issue gets a numbered colored box in the screenshot:
      RED   = high severity (likely a real bug — e.g. two static siblings overlapping)
      ORANGE = medium severity (possibly intentional — e.g. absolute-positioned overlap)
      YELLOW = low severity (probably intentional — e.g. z-indexed stacking)

    YOU decide whether to fix each issue based on:
      - intentionality_score: 0.0 = definitely a bug, 1.0 = definitely intentional
      - The annotated screenshot showing exactly where the problem is
      - The note field explaining the likely cause

    WORKFLOW:
      1. Build the site and start the dev server (e.g. npm run dev → localhost:3000)
      2. Call this tool with the URL
      3. Read the screenshot_path image to see annotated issues
      4. Read the issues list to get structured details
      5. Fix issues where intentionality_score < 0.4 and severity is high/medium
      6. Ignore issues where intentionality_score > 0.6 (likely design choices)
      7. Re-run this tool after fixes to confirm resolution

    Args:
        url: Page URL to check. Must be reachable (e.g. "http://localhost:3000",
             "http://localhost:3000/about"). Start the dev server first.
        viewport_width: Viewport width in pixels. Default 1440 (desktop).
                        Use 390 for iPhone-sized mobile check.
        mobile: Shorthand for viewport_width=390. If True, overrides viewport_width.
    """
    if mobile:
        viewport_width = 390

    instructions = (
        "READ THE SCREENSHOT FIRST using your Read tool (it has vision). "
        "The annotated image shows colored numbered boxes at each issue location. "
        "RED = high severity, ORANGE = medium, YELLOW = low. "
        "Then review the issues list. For each issue:\n"
        "  - intentionality_score < 0.3 → almost certainly a bug, fix it\n"
        "  - intentionality_score 0.3-0.6 → visually verify, fix if it looks wrong\n"
        "  - intentionality_score > 0.6 → probably intentional design, leave it\n"
        "After fixing, call this tool again to confirm issues are resolved."
    )

    # Remote mode + localhost URL: the server can't reach the user's machine.
    # Instead, give the agent a ready-to-run bash command — it runs locally and
    # has Bash tool access, so it can execute the checker on the user's machine
    # and read back the result + screenshot directly.
    if _remote_mode and _is_local_url(url):
        repo_dir = os.environ.get("SUPERPOWER_LOCAL_REPO", "~/Documents/GitHub/Superpowering-Agents")
        bash_cmd = (
            f"cd {repo_dir} && "
            f"python -m src.layout_checker {url} {viewport_width}"
        )
        return {
            "local_execution_required": True,
            "reason": (
                f"{url} is a local address — the remote MCP server cannot reach it. "
                "The agent runs locally and can execute the checker directly via Bash."
            ),
            "instructions": (
                f"Run this command with your Bash tool:\n\n"
                f"    {bash_cmd}\n\n"
                "It prints JSON to stdout. Parse the result:\n"
                "  1. Read screenshot_path with your Read tool to see the annotated image\n"
                "  2. Review the issues[] list with intentionality_score to decide what to fix\n"
                "  3. " + instructions
            ),
            "bash_command": bash_cmd,
        }

    result = check_layout(url=url, viewport_width=viewport_width)

    if "error" in result:
        return result

    if _remote_mode:
        screenshot_bytes = Path(result["screenshot_path"]).read_bytes()
        payload = {
            "url": result["url"],
            "viewport_width": result["viewport_width"],
            "summary": result["summary"],
            "stats": result["stats"],
            "issues": result["issues"],
            "instructions": instructions,
        }
        return [json.dumps(payload), Image(data=screenshot_bytes, format="png")]

    return {
        "url": result["url"],
        "viewport_width": result["viewport_width"],
        "summary": result["summary"],
        "stats": result["stats"],
        "issues": result["issues"],
        "screenshot_path": result["screenshot_path"],
        "instructions": instructions,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Superpowering Agents MCP server")
    parser.add_argument("--sse", action="store_true", help="Run with SSE transport (remote/hosted)")
    parser.add_argument("--http", action="store_true", help="Run with streamable HTTP transport (for Claude Code remote)")
    parser.add_argument("--host", default=os.environ.get("MCP_HOST", "0.0.0.0"), help="Host to bind (remote mode, default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8001")), help="Port to bind (remote mode, default: 8001)")
    args = parser.parse_args()

    if args.http:
        import json as _json
        import uvicorn
        from starlette.routing import Route
        from starlette.requests import Request as StarletteRequest

        app = mcp.streamable_http_app()
        api_key = os.environ.get("MCP_API_KEY")

        # OAuth 2.0 Protected Resource Metadata (RFC 9728 / MCP auth spec).
        # Advertising this endpoint tells MCP clients (e.g. Codex) that the
        # server uses Bearer tokens, resolving "auth unsupported" errors when
        # the endpoint is absent.
        server_url = os.environ.get("MCP_SERVER_URL", f"http://{args.host}:{args.port}")

        async def oauth_metadata(request: StarletteRequest) -> Response:
            metadata = {
                "resource": server_url,
                "authorization_servers": [],
                "bearer_methods_supported": ["header"],
                "scopes_supported": [],
            }
            return Response(
                _json.dumps(metadata),
                status_code=200,
                media_type="application/json",
                headers={"Access-Control-Allow-Origin": "*"},
            )

        app.add_route("/.well-known/oauth-protected-resource", oauth_metadata, methods=["GET"])
        app.add_route("/.well-known/oauth-authorization-server", oauth_metadata, methods=["GET"])

        if api_key:
            class BearerAuthMiddleware(BaseHTTPMiddleware):
                async def dispatch(self, request: Request, call_next: Callable) -> Response:
                    # Always allow auth discovery endpoints through unauthenticated.
                    if request.url.path.startswith("/.well-known/"):
                        return await call_next(request)
                    auth = request.headers.get("Authorization", "")
                    if not auth.startswith("Bearer ") or auth[len("Bearer "):] != api_key:
                        return Response(
                            '{"error":"invalid_token","error_description":"Invalid or missing bearer token"}',
                            status_code=401,
                            media_type="application/json",
                        )
                    return await call_next(request)

            app.add_middleware(BearerAuthMiddleware)
        uvicorn.run(app, host=args.host, port=args.port)
    elif args.sse:
        mcp.run(transport="sse", host=args.host, port=args.port)
    else:
        mcp.run()
