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

from src.config import settings
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from src.pipeline import (
    analyze_all_references,
    build_context_system_prompt,
    build_reference_images_for_remote,
    build_reference_surface_analysis,
    get_dom_summaries_for_domains,
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
    find_provider,
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


# ── Workflow state tracking ──────────────────────────────────────────────
# Tracks which steps have been completed in the mandatory workflow sequence.
# This prevents the agent from skipping steps (e.g. jumping straight to
# code without selecting primitives or running design review).

class _WorkflowState:
    """Tracks completed workflow steps per session."""

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.context_called: bool = False
        self.context_domains: list[str] = []
        self.catalog_browsed: bool = False
        self.primitives_selected: bool = False
        self.selected_primitive_ids: list[str] = []
        self.design_reviewed: bool = False
        self.design_review_passed: bool = False
        self.images_called: int = 0
        self.review_build_called: bool = False
        self.review_build_grade: str | None = None
        self.review_build_iterations: int = 0
        self.check_layout_called: bool = False
        self.check_layout_issues_high: int = 0

    def check_prerequisite(self, step: str) -> str | None:
        """Return an error message if prerequisites for a step aren't met, else None.

        Hard blocks (WORKFLOW ERROR) prevent the tool from executing.
        Every step in the mandatory workflow is enforced — skipping any step
        returns an error and the tool refuses to proceed.
        """
        if step == "primitive_catalog":
            if not self.context_called:
                return (
                    "WORKFLOW ERROR: You must call superpower_context (or superpower_retrieve) "
                    "BEFORE browsing the primitive catalog. The context provides reference images "
                    "and DOM analysis that should inform your primitive selection. "
                    "Call superpower_context first."
                )
        elif step == "primitive_select":
            if not self.catalog_browsed:
                return (
                    "WORKFLOW ERROR: You must call superpower_primitive_catalog BEFORE selecting "
                    "primitives. Browse the full catalog (including discovery_spotlight) to make "
                    "informed selections. Call superpower_primitive_catalog first."
                )
        elif step == "design_review":
            if not self.primitives_selected:
                return (
                    "WORKFLOW ERROR: You must call superpower_primitive_select BEFORE running "
                    "design review. Select your primitives first so the review can check if "
                    "your section descriptions mention using them. "
                    "Call superpower_primitive_select first."
                )
        elif step == "build":
            # HARD BLOCK — every prerequisite must be completed before building,
            # reviewing, or checking layout. No advisory warnings — these are
            # mandatory steps that cannot be skipped.
            missing: list[str] = []
            if not self.context_called:
                missing.append("superpower_context (retrieve design references)")
            if not self.catalog_browsed:
                missing.append("superpower_primitive_catalog (browse primitives)")
            if not self.primitives_selected:
                missing.append("superpower_primitive_select (select primitives)")
            if not self.design_reviewed:
                missing.append(
                    "superpower_design_review (validate design plan — you MUST run design "
                    "review and get a PASS verdict before building)"
                )
            elif not self.design_review_passed:
                missing.append(
                    "superpower_design_review PASSING (your last design review did NOT pass — "
                    "revise your section plan based on the critic's feedback and re-submit "
                    "until the verdict is PASS)"
                )
            if self.images_called < 2:
                missing.append(
                    f"superpower_images (called {self.images_called}x, need at least 2 calls — "
                    "you need hero images, people/team photos, and industry-specific imagery)"
                )
            if missing:
                return (
                    "WORKFLOW ERROR: You cannot build, review, or check layout until ALL "
                    "mandatory workflow steps are completed. Missing steps:\n" +
                    "\n".join(f"  - {m}" for m in missing) +
                    "\n\nThese are HARD REQUIREMENTS, not suggestions. Go back and complete "
                    "every missing step before proceeding. The workflow exists to prevent "
                    "generic, template-grade output."
                )
        return None


_workflow = _WorkflowState()


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
    # Reset workflow for new context call (new project)
    _workflow.reset()

    intent, results = run_retrieval(prompt, page_type, industry, business_model, brand_tier, top_k, no_vector)
    if style_profile:
        intent.industry_style_profile = style_profile
    corpus_coverage = get_corpus_coverage(intent)

    # Track workflow state
    _workflow.context_called = True
    _workflow.context_domains = [r.domain for r in results]

    # Import the disposition prompt — this MUST always be returned so the LLM
    # gets the design personality, quality standards, and visual density guidance
    # regardless of whether primitives are auto-selected or manually chosen.
    from src.pipeline import CONTEXT_SYSTEM_PROMPT

    primitive_bundle = None
    if auto_primitives:
        system_prompt, primitive_bundle = build_context_system_prompt(prompt, intent, results)
    else:
        # Even in manual mode, the disposition / personality / quality guidance
        # is critical. Without it the LLM produces generic SaaS-looking output.
        system_prompt = CONTEXT_SYSTEM_PROMPT

    instructions = (
        "Follow the system_prompt CAREFULLY — it contains your design disposition, "
        "quality standards, and mandatory workflow. The server enforces workflow "
        "order — it will block you if you skip steps. Study reference_surface_analysis "
        "to match the visual richness of your references. Install and use the actual "
        "npm packages from your primitive selection."
    )

    # Build aggregate DOM surface analysis for all references
    ref_domains = [r.domain for r in results]
    surface_analysis = build_reference_surface_analysis(ref_domains)

    # Vision-based reference analysis: extract structured CSS parameters from screenshots
    # This is the key insight — text-based visual specs get followed 100% of the time,
    # while image-based references get ignored. So we convert images → text specs.
    vision_specs = analyze_all_references(results)

    if _remote_mode:
        references, image_bytes_list = build_reference_images_for_remote(results)
        payload = {
            "system_prompt": system_prompt,
            "intent": intent_to_info(intent).model_dump(),
            "corpus_coverage": corpus_coverage,
            "num_references": len(references),
            "references": references,
            "reference_visual_specs": vision_specs,
            "reference_surface_analysis": surface_analysis,
            "primitives": primitive_bundle,
            "instructions": instructions,
        }
        content: list = [json.dumps(payload)]
        for img_bytes in image_bytes_list:
            content.append(Image(data=img_bytes, format="jpeg"))
        return content

    references = save_reference_images(results)
    return {
        "system_prompt": system_prompt,
        "intent": intent_to_info(intent).model_dump(),
        "corpus_coverage": corpus_coverage,
        "num_references": len(references),
        "references": references,
        "reference_visual_specs": vision_specs,
        "reference_surface_analysis": surface_analysis,
        "primitives": primitive_bundle,
        "instructions": instructions,
    }


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

    # Track workflow — retrieve counts as context for workflow purposes
    _workflow.context_called = True
    _workflow.context_domains.extend([r.domain for r in results])

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

    NOTE: This returns lean summaries (id, name, category, score, traits) to keep
    the payload small. Full variant details and implementation recipes are returned
    by superpower_primitive_select for the primitives you actually choose.
    """
    # Workflow enforcement
    prereq_error = _workflow.check_prerequisite("primitive_catalog")
    if prereq_error:
        return {"workflow_error": prereq_error}

    _workflow.catalog_browsed = True

    registry = load_primitive_registry()
    discovery = get_discovery_highlights(registry) if not category else []

    # Return lean provider summaries — strip full variant dicts to keep payload small
    # Full details are returned by superpower_primitive_select for selected primitives
    lean_providers = []
    for p in list_providers(category):
        lean = {
            "id": p.get("id"),
            "category": p.get("category"),
            "name": p.get("name"),
            "package": p.get("package", ""),
            "score": p.get("score", 0),
            "when_to_use": p.get("when_to_use", []),
            "traits": p.get("traits", []),
        }
        # Include usage_rule if present (one-liner guidance)
        variants = p.get("variants", {})
        if isinstance(variants, dict):
            for key in ("usage_rule", "anti_slop_rule", "anti_slop_note", "anti_template_note", "enforcement_rule"):
                if key in variants:
                    lean["key_rule"] = variants[key]
                    break
        lean_providers.append(lean)

    # Lean font pairs — just id, display, body, tone
    lean_fonts = [
        {"id": fp.get("id"), "display": fp.get("display"), "body": fp.get("body"), "tone": fp.get("tone", [])}
        for fp in registry.get("font_pairs", [])
    ]

    # Lean motion primitives — just id, type, description (no code_snippet)
    lean_motions = [
        {"id": m.get("id"), "type": m.get("type"), "description": m.get("description", "")[:120]}
        for m in registry.get("motion_primitives", [])
    ]

    # Lean archetypes — just id and key fields
    lean_archetypes = [
        {"id": a.get("id"), "layout": a.get("layout"), "hero": a.get("hero"),
         "section_rhythm": a.get("section_rhythm"), "signature_moves": a.get("signature_moves", [])}
        for a in registry.get("variation_archetypes", [])
    ]

    return {
        "version": registry.get("version"),
        "category": category,
        "discovery_spotlight": discovery,
        "discovery_note": (
            "These providers are from categories most developers skip. "
            "Pick at least 2-3 from discovery_spotlight alongside your standard choices. "
            "They are what separate template-looking output from custom-feeling output."
        ) if discovery else None,
        "providers": lean_providers,
        "font_pairs": lean_fonts,
        "motion_primitives": lean_motions,
        "variation_archetypes": lean_archetypes,
    }


@mcp.tool()
def superpower_primitive_select(
    provider_ids: list[str],
    font_pair_id: str | None = None,
    motion_ids: list[str] | None = None,
    archetype_id: str | None = None,
    tags: list[str] | None = None,
    reference_domains: list[str] | None = None,
) -> dict:
    """Build a primitive bundle from explicit primitive IDs chosen by the client LLM.

    If reference_domains is provided (list of domains from superpower_context),
    this tool will compare your selection against what those references actually
    use in their DOM and warn you about high-frequency techniques you're missing.
    This prevents under-designing relative to your references.
    """
    # Workflow enforcement
    prereq_error = _workflow.check_prerequisite("primitive_select")
    if prereq_error:
        return {"workflow_error": prereq_error}

    # Auto-fill reference_domains from context if not provided
    if not reference_domains and _workflow.context_domains:
        reference_domains = _workflow.context_domains

    bundle = build_manual_primitive_bundle(
        provider_ids=provider_ids,
        font_pair_id=font_pair_id,
        motion_ids=motion_ids,
        archetype_id=archetype_id,
        tags=tags,
    )
    addendum = build_primitive_prompt_addendum(bundle)

    # Track workflow state
    _workflow.primitives_selected = True
    _workflow.selected_primitive_ids = list(provider_ids)

    result: dict = {
        "primitives": bundle,
        "prompt_addendum": addendum,
        "selected_provider_ids": provider_ids,
        "selected_motion_ids": motion_ids or [],
        "selected_font_pair_id": font_pair_id,
        "selected_archetype_id": archetype_id,
    }

    # Score selection against reference DOM data
    if reference_domains:
        surface_analysis = build_reference_surface_analysis(reference_domains)
        technique_freq = surface_analysis.get("technique_frequency", {})
        primitive_freq = surface_analysis.get("primitive_frequency", {})
        n_refs = len(surface_analysis.get("per_reference", {})) or 1

        # Check which high-frequency reference techniques are NOT covered
        # by the selected providers
        selected_categories = set()
        selected_ids_set = set(provider_ids)
        for pid in provider_ids:
            provider = find_provider(pid)
            if provider:
                selected_categories.add(provider.get("category", ""))

        warnings: list[str] = []
        # Map surface techniques to primitive categories
        technique_to_category = {
            "glassmorphism": "surface.glassmorphism",
            "mesh-gradient": "background.mesh-gradient",
            "aurora-gradient": "background.aurora-gradient",
            "noise-grain": "background.noise-texture",
            "dot-grid": "background.dot-grid",
            "outlined-text": "text-effects.outlined-text",
            "image-filters": "image-effects.css-svg-filters",
            "oklch-colors": "theming.oklch-palette",
        }
        for technique, count in technique_freq.items():
            ratio = count / n_refs
            if ratio < 0.4:
                continue
            mapped_id = technique_to_category.get(technique)
            if mapped_id and mapped_id not in selected_ids_set:
                warnings.append(
                    f"MISSING: {count}/{n_refs} of your references use {technique}, "
                    f"but you haven't selected '{mapped_id}'. This is a significant "
                    f"gap — your output will look less polished than the references."
                )

        # Check for high-frequency detected primitives not selected
        skip_prims = {"tailwind", "bootstrap", "webflow", "wordpress", "shopify"}
        for prim, count in primitive_freq.items():
            if prim in skip_prims:
                continue
            ratio = count / n_refs
            if ratio < 0.4:
                continue
            if prim not in selected_ids_set:
                warnings.append(
                    f"GAP: {count}/{n_refs} references use '{prim}' but it's not in your selection."
                )

        if warnings:
            result["coverage_warnings"] = warnings
            result["coverage_note"] = (
                f"Your selection is missing {len(warnings)} technique(s) that your references "
                f"commonly use. Award-winning sites layer 3-5 surface techniques simultaneously. "
                f"Consider adding the missing primitives to match your references' visual richness."
            )
        else:
            result["coverage_note"] = "Good coverage — your selection aligns well with reference techniques."

    return result


@mcp.tool()
def superpower_design_review(
    sections: list[str],
    sub_agent_verdict: str | None = None,
    reference_domains: list[str] | None = None,
    selected_primitives: list[str] | None = None,
) -> dict:
    """Pre-build creative quality gate — uses YOUR sub-agent as the design critic.

    TWO MODES:

    MODE 1 — GET REVIEW PROMPT (no sub_agent_verdict):
      Pass your section descriptions. Returns a critic disposition prompt.
      You MUST spawn a sub-agent with this prompt to review your plan.
      The sub-agent is a fresh perspective — it catches the boring patterns
      you've gone blind to. Do NOT skip the sub-agent. Do NOT review your
      own work — you are biased toward what you just designed.

    MODE 2 — RECORD VERDICT (with sub_agent_verdict):
      After your review sub-agent reports back, call this tool again with
      sub_agent_verdict set to "PASS", "NEEDS WORK", or "FAIL".
      This updates workflow state so you can proceed to building.
      If the verdict is not PASS, revise your plan and repeat.

    The sub-agent pattern:
      1. Call superpower_design_review(sections=[...]) → get critic_prompt
      2. Spawn a sub-agent with the critic_prompt as its task
      3. Read the sub-agent's response — it grades each section
      4. If PASS → call superpower_design_review(sections=[...], sub_agent_verdict="PASS")
      5. If not PASS → revise sections based on feedback, go to step 1

    Args:
        sections: Natural-language descriptions of each section's visual plan.
        sub_agent_verdict: "PASS", "NEEDS WORK", or "FAIL" from your review sub-agent.
        reference_domains: Domains from superpower_context (for comparison scoring).
        selected_primitives: Provider IDs from superpower_primitive_select.
    """
    # Workflow enforcement
    prereq_error = _workflow.check_prerequisite("design_review")
    if prereq_error:
        return {"workflow_error": prereq_error}

    # Auto-fill from workflow state if not provided
    if not reference_domains and _workflow.context_domains:
        reference_domains = _workflow.context_domains
    if not selected_primitives and _workflow.selected_primitive_ids:
        selected_primitives = _workflow.selected_primitive_ids

    # ── MODE 2: Record verdict from sub-agent ──
    if sub_agent_verdict:
        verdict = sub_agent_verdict.upper().strip()
        _workflow.design_reviewed = True
        _workflow.design_review_passed = verdict == "PASS"

        if verdict == "PASS":
            return {
                "status": "DESIGN REVIEW PASSED",
                "instructions": "Your design plan passed review. Proceed to building.",
            }
        else:
            return {
                "status": f"DESIGN REVIEW: {verdict}",
                "instructions": (
                    "Your design plan did not pass. Revise your section descriptions "
                    "based on the sub-agent's feedback, then call superpower_design_review "
                    "again with the updated sections (without sub_agent_verdict) to get "
                    "a new review. Keep iterating until the sub-agent says PASS."
                ),
            }

    # ── MODE 1: Generate critic prompt for sub-agent ──

    section_block = ""
    for i, desc in enumerate(sections, 1):
        section_block += f"\n--- SECTION {i} ---\n{desc}\n"

    primitives_context = ""
    if selected_primitives:
        primitives_context = (
            f"\nThe designer selected these primitives: {', '.join(selected_primitives)}. "
            "Consider whether the section plans use them in meaningful, creative ways "
            "or just as checkboxes.\n"
        )

    critic_prompt = f"""You are a ruthlessly honest creative director at a world-class design agency.

A designer on your team has written a section-by-section plan for a website. They have NOT built it yet — this is your chance to catch boring, safe, template-grade thinking BEFORE it becomes hours of wasted work.

Here are their planned sections:
{section_block}
{primitives_context}
For EACH section, evaluate on these five dimensions:

1. **Would this turn heads?** If someone scrolled past this on Awwwards, would they stop or keep scrolling?

2. **Is this DESIGN or just LAYOUT?** Cards in a grid with icons is layout. A creative idea expressed through visual technique is design. Does this section have an IDEA?

3. **Does it have sensory richness?** Can you imagine the texture, the depth, the light? Or is it flat shapes on flat colors? Great sections layer: background treatment + surface depth + interactive response + typographic drama.

4. **Is it structurally surprising?** Does the layout break expectations or is it the predictable grid-and-columns?

5. **Could any AI have generated this?** The harshest test. What makes this specific to THIS brand?

Grade each section:
- **STRONG**: Has a creative idea that would look distinctive on Awwwards
- **ADEQUATE**: Competent but safe. One more bold choice would elevate it
- **NEEDS WORK**: Generic. Seen it a thousand times. Content without design
- **TEMPLATE-GRADE**: What a free website builder produces

Then give an overall verdict:
- **PASS**: No template-grade sections, majority strong/adequate, at least 2 sections are genuinely exciting
- **NEEDS WORK**: Some sections are template-grade or the plan lacks creative ambition overall
- **FAIL**: Most sections are generic. Needs a creative rethink, not tweaks

Be direct and constructive. For every section that needs work, say SPECIFICALLY what would elevate it — not "add more visual richness" but what KIND, what technique, what creative idea would transform it.

End with your overall verdict: PASS, NEEDS WORK, or FAIL."""

    return {
        "critic_prompt": critic_prompt,
        "num_sections": len(sections),
        "instructions": (
            "MANDATORY: Spawn a sub-agent with the critic_prompt above as its task. "
            "The sub-agent acts as a fresh creative director reviewing your plan. "
            "Do NOT review your own work — you are biased toward what you just designed.\n\n"
            "After the sub-agent reports back:\n"
            "  - If verdict is PASS → call superpower_design_review(sections=..., sub_agent_verdict='PASS')\n"
            "  - If verdict is NEEDS WORK or FAIL → revise your sections based on the feedback, "
            "then call superpower_design_review again with the new sections (no sub_agent_verdict) "
            "to get a fresh review. Keep iterating until PASS.\n\n"
            "Do NOT skip this step. Do NOT start building until the review passes."
        ),
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
    _workflow.images_called += 1

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
async def superpower_review_build(
    url: str,
    company_name: str = "",
    sub_agent_verdict: str | None = None,
) -> list | dict:
    """MANDATORY post-build quality review — screenshots the page, then YOU review it.

    TWO MODES:

    MODE 1 — SCREENSHOT + CRITIC PROMPT (no sub_agent_verdict):
      Screenshots the built page and returns:
      - screenshot_path: Read this image to see the actual rendered page
      - critic_prompt: The disposition for your review sub-agent

      You MUST:
      1. Read the screenshot with your Read tool
      2. Spawn a review sub-agent that also reads the screenshot
      3. The sub-agent evaluates every visible section as a design critic
      4. Report the verdict back via MODE 2

    MODE 2 — RECORD VERDICT (with sub_agent_verdict):
      Pass "PASS" or "FAIL" to update workflow state.
      - PASS: overall grade B+ equivalent, no terrible sections. Proceed.
      - FAIL: sections need fixing. Fix them, rebuild, call MODE 1 again.
      The iteration loop continues until PASS.

    Args:
        url: The localhost URL to review (e.g. http://localhost:3000)
        company_name: The company name for context
        sub_agent_verdict: "PASS" or "FAIL" from your review sub-agent.
    """
    # ── MODE 2: Record verdict ──
    if sub_agent_verdict:
        verdict = sub_agent_verdict.upper().strip()
        _workflow.review_build_called = True
        _workflow.review_build_iterations += 1
        _workflow.review_build_grade = "B" if verdict == "PASS" else "D"

        if verdict == "PASS":
            return {
                "review_status": "PASSED",
                "iteration": _workflow.review_build_iterations,
                "instructions": "Review PASSED. Proceed to check other pages.",
            }
        else:
            return {
                "review_status": "FAILED — MUST ITERATE",
                "iteration": _workflow.review_build_iterations,
                "instructions": (
                    f"Review FAILED (iteration {_workflow.review_build_iterations}). "
                    "Fix the issues your review sub-agent identified, rebuild, then "
                    "call superpower_review_build again (without sub_agent_verdict) "
                    "to get a fresh screenshot and re-review. Keep iterating until PASS."
                ),
            }

    # ── MODE 1: Take screenshot + return critic prompt ──

    # Hard block: all pre-build workflow steps must be completed
    prereq_error = _workflow.check_prerequisite("build")
    if prereq_error:
        return {"workflow_error": prereq_error}

    import asyncio

    try:
        from playwright.sync_api import sync_playwright

        def _take_screenshot() -> bytes:
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(viewport={"width": 1440, "height": 900})
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(3000)
                screenshot = page.screenshot(full_page=True, type="jpeg", quality=85)
                browser.close()
                return screenshot

        screenshot_bytes = await asyncio.to_thread(_take_screenshot)
    except Exception as e:
        return {"error": f"Could not screenshot {url}: {e}"}

    # Save screenshot to temp file for the agent to read
    import tempfile
    screenshot_path = tempfile.NamedTemporaryFile(
        suffix=".jpg", prefix="review_build_", delete=False
    ).name
    with open(screenshot_path, "wb") as f:
        f.write(screenshot_bytes)

    critic_prompt = f"""You are a brutally honest senior design critic at a top-tier agency.

You are looking at a screenshot of a built website for "{company_name or 'a company'}".
Read the screenshot at: {screenshot_path}

For EACH visible section on the page, evaluate it as a creative director would:

- Does this section make you FEEL something, or is it just filling space?
- Is there a creative IDEA here, or is it just content organized into rectangles?
- Does it have sensory richness — texture, depth, layering, typographic drama?
- Is the layout surprising or predictable?
- Would you be proud to put this in your agency's portfolio?

Grade each section A through F:
- A: Exceptional. Portfolio-worthy. Has a distinctive creative idea.
- B: Good. Polished and intentional. Not generic.
- C: Average. Forgettable. Could be any website.
- D: Below average. Generic cards, flat backgrounds, no visual thinking.
- F: Broken or embarrassingly template-grade.

After grading every section, give an OVERALL verdict:
- PASS: No D/F sections, overall quality is B or better
- FAIL: Has D/F sections or the overall quality is C or below

For every section graded C or below, give SPECIFIC fixes — not "make it better" but
exactly what change (CSS, layout, technique) would elevate it.

Be harsh. The designer needs honest feedback, not encouragement."""

    # In remote mode, embed the image directly
    if _remote_mode:
        payload = {
            "url": url,
            "critic_prompt": critic_prompt,
            "instructions": (
                "MANDATORY: Read the screenshot, then spawn a review sub-agent with the "
                "critic_prompt. The sub-agent reads the same screenshot and critiques every "
                "section. Based on its feedback:\n"
                "  - If PASS → call superpower_review_build(url=..., sub_agent_verdict='PASS')\n"
                "  - If FAIL → fix the issues, rebuild, call superpower_review_build again\n"
                "Keep iterating until PASS."
            ),
        }
        return [json.dumps(payload), Image(data=screenshot_bytes, format="jpeg")]

    return {
        "url": url,
        "screenshot_path": screenshot_path,
        "critic_prompt": critic_prompt,
        "instructions": (
            f"MANDATORY: Read the screenshot at {screenshot_path} with your Read tool. "
            "Then spawn a review sub-agent with the critic_prompt above. The sub-agent "
            "should also read the screenshot and critique every visible section.\n\n"
            "Based on its feedback:\n"
            "  - If PASS → call superpower_review_build(url=..., sub_agent_verdict='PASS')\n"
            "  - If FAIL → fix the issues it identified, rebuild, then call "
            "superpower_review_build again (without sub_agent_verdict) for a fresh screenshot.\n\n"
            "Keep iterating until PASS. Do NOT declare the site complete until every page passes."
        ),
    }


@mcp.tool(structured_output=False)
async def superpower_check_layout(
    url: str,
    viewport_width: int = 1440,
    mobile: bool = False,
) -> list | dict:
    """Detect visual layout issues AND visual richness problems on a rendered page.

    Launches a headless Chromium browser, navigates to the URL, and runs TWO
    detection passes:

    1. LAYOUT DETECTION — finds rendering problems: overlapping elements,
       content overflow, collapsed containers, and off-viewport content.

    2. VISUAL RICHNESS DETECTION — finds template-grade sections: sections
       without background treatments, missing surface depth (no glassmorphism,
       shadows, or spotlight effects), small typography, lack of animation
       attributes, and overall page monotony. Sections scoring 5/10 or below
       on richness are flagged as needing more visual ambition.

    Each issue gets a numbered colored box in the screenshot:
      RED   = high severity (layout bug OR severely template-grade section)
      ORANGE = medium severity (possible layout issue OR mildly under-designed)
      YELLOW = low severity (probably intentional design choice)

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

    # Hard block: all pre-build workflow steps must be completed
    prereq_error = _workflow.check_prerequisite("build")
    if prereq_error:
        return {"workflow_error": prereq_error}

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

    import asyncio
    result = await asyncio.to_thread(check_layout, url=url, viewport_width=viewport_width)

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

    # Track layout check completion and high-severity issue count
    _workflow.check_layout_called = True
    high_count = sum(
        1 for issue in result.get("issues", [])
        if issue.get("severity") == "high"
    )
    _workflow.check_layout_issues_high = high_count

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
