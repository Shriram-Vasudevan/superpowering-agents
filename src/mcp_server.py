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
    build_assembler_prompt,
    build_context_system_prompt,
    build_reference_images_for_remote,
    build_reference_surface_analysis,
    build_section_builder_prompt,
    format_corpus_peer_evidence,
    format_industry_context,
    generate_creative_provocations,
    get_dom_summaries_for_domains,
    get_industry_vocab,
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
    build_primitive_bundle,
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
        # Rich context stored from superpower_context for section builders
        self.font_pair: dict = {}
        self.color_palette: str = ""
        self.primitive_bundle: dict = {}
        self.primitive_addendum: str = ""
        self.industry: str | None = None
        self.vision_specs: list[dict] = []

    def check_prerequisite(self, step: str) -> str | None:
        """Return an error message if prerequisites for a step aren't met, else None.

        Enforces a lightweight sequence: context must come first, design review
        requires context, and build/review tools require context + images.
        Primitive catalog/select are available but not hard-gated.
        """
        if step == "primitive_catalog":
            if not self.context_called:
                return (
                    "Call superpower_context (or superpower_retrieve) first to get "
                    "design references. The context informs primitive selection."
                )
        elif step == "primitive_select":
            if not self.context_called:
                return (
                    "Call superpower_context first. You need references before "
                    "selecting primitives."
                )
        elif step == "design_review":
            if not self.context_called:
                return (
                    "Call superpower_context first. The design review needs "
                    "reference context to evaluate your brief."
                )
        elif step == "section_context":
            if not self.context_called:
                return (
                    "Call superpower_context first. Section context builds on "
                    "the references and primitives from context."
                )
            if not self.design_reviewed or not self.design_review_passed:
                return (
                    "Your design brief must pass superpower_design_review BEFORE "
                    "you can get section builder context. Write a section-by-section "
                    "design brief with concepts and metaphors, then call "
                    "superpower_design_review to validate it. The toolkit (npm packages, "
                    "imports, fonts) is only released after the brief passes review."
                )
            if self.images_called < 2:
                return (
                    f"Call superpower_images at least 2 more times (called {self.images_called}x). "
                    "You need hero backgrounds, team photos, and industry imagery before "
                    "section builders can start."
                )
        elif step == "build":
            missing: list[str] = []
            if not self.context_called:
                missing.append("superpower_context (retrieve design references)")
            if not self.design_reviewed:
                missing.append(
                    "superpower_design_review (validate your design brief before building)"
                )
            elif not self.design_review_passed:
                missing.append(
                    "superpower_design_review PASSING (revise your brief until it passes)"
                )
            if self.images_called < 2:
                missing.append(
                    f"superpower_images (called {self.images_called}x, need at least 2 — "
                    "hero backgrounds, team photos, and industry imagery)"
                )
            if missing:
                return (
                    "Cannot build/review until these steps are done:\n" +
                    "\n".join(f"  - {m}" for m in missing)
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
) -> list | dict:
    """Get design references, industry vocabulary, and creative provocations.

    This is Step 1. It does NOT give you packages or code tools — those come
    later via superpower_section_context, AFTER your design brief passes review.

    Returns:
    - system_prompt: Your creative disposition (internalize this)
    - Reference screenshots + visual specs (study these deeply)
    - Industry vocabulary and creative provocations (think in these metaphors)

    YOUR NEXT STEPS after calling this:
    1. Study every reference image — extract color, typography, density, texture
    2. Call superpower_images 3+ times (hero backgrounds, team photos, industry imagery)
    3. WRITE A DESIGN BRIEF — for each section, describe the CONCEPT (visual metaphor),
       LAYOUT, INTERACTION, and MOOD. Plan multiple pages that fit the industry.
       This is the most important step. Think in metaphors, not layouts.
    4. Call superpower_design_review with your brief — a critic validates it
    5. ONLY AFTER the brief passes: call superpower_section_context to get the
       build toolkit (npm packages, fonts, imports) for each sub-agent

    DO NOT start writing code until your design brief passes review.
    DO NOT install npm packages yet — the toolkit comes from superpower_section_context.
    """
    _workflow.reset()

    intent, results = run_retrieval(prompt, page_type, industry, business_model, brand_tier, top_k, no_vector)
    if style_profile:
        intent.industry_style_profile = style_profile
    corpus_coverage = get_corpus_coverage(intent)

    _workflow.context_called = True
    _workflow.context_domains = [r.domain for r in results]

    # Build the system prompt: disposition + peer evidence + industry vocab + provocations
    # NOTE: No primitive toolkit here — that's gated behind design review
    from src.pipeline import CONTEXT_SYSTEM_PROMPT

    industry_context = format_industry_context(intent.industry)
    provocations = generate_creative_provocations(intent.industry, results)
    corpus_evidence = format_corpus_peer_evidence()

    parts = [CONTEXT_SYSTEM_PROMPT]
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
    system_prompt = "\n\n".join(parts)

    # Build aggregate DOM surface analysis
    ref_domains = [r.domain for r in results]
    surface_analysis = build_reference_surface_analysis(ref_domains)

    # Vision-based reference analysis: CSS parameters from screenshots
    vision_specs = analyze_all_references(results)

    # Industry vocabulary for the response
    vocab = get_industry_vocab(intent.industry)

    # INTERNALLY compute and store primitive bundle for later release
    # via superpower_section_context (after design review passes)
    primitive_bundle = build_primitive_bundle(prompt, intent, results)
    _workflow.industry = intent.industry
    _workflow.vision_specs = vision_specs
    _workflow.primitive_bundle = primitive_bundle
    _workflow.font_pair = primitive_bundle.get("font_pair", {})
    _workflow.primitive_addendum = build_primitive_prompt_addendum(primitive_bundle)
    # Extract color palette from vision specs
    colors = set()
    for spec in vision_specs:
        vs = spec.get("visual_spec", {})
        palette = vs.get("color_palette", "")
        if palette:
            colors.add(palette)
    if colors:
        _workflow.color_palette = " | ".join(list(colors)[:3])

    instructions = (
        "DO NOT START BUILDING YET. Read the system_prompt — it contains your "
        "creative disposition. Study every reference image. Then:\n\n"
        "1. Call superpower_images 3+ times for real Unsplash photos\n"
        "2. Write a DESIGN BRIEF — section-by-section concepts with visual metaphors, "
        "not 'hero with heading' but 'mission control screen with telemetry readouts'\n"
        "3. Call superpower_design_review with your brief sections\n"
        "4. After the brief PASSES review, call superpower_section_context to get "
        "the build toolkit (npm packages, fonts, imports) for each sub-agent\n\n"
        "The toolkit is NOT available until your design brief passes review. "
        "This is structural — the server will block you. Plan first, build second."
    )

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
            "industry_vocabulary": vocab,
            "creative_provocations": provocations,
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
        "industry_vocabulary": vocab,
        "creative_provocations": provocations,
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
    """Browse the full primitive catalog to customize your toolkit.

    OPTIONAL — superpower_context auto-selects primitives based on your industry
    and references. Use this tool if you want to explore alternatives or add
    packages from categories not auto-selected.

    Check discovery_spotlight first — these are high-impact categories that make
    the difference between template-looking and custom-feeling output (text-effects,
    background shaders, image effects, surface treatments).

    Returns lean summaries. Call superpower_primitive_select to lock in your choices.
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
    """Override auto-selected primitives with explicit choices.

    OPTIONAL — superpower_context auto-selects a toolkit. Use this to customize:
    swap a font pair, add a specific package, or choose a different archetype.

    If reference_domains is provided, compares your selection against what those
    references actually use in their DOM and warns about gaps.
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
    # Store for section builders
    _workflow.primitive_bundle = bundle
    _workflow.primitive_addendum = addendum
    _workflow.font_pair = bundle.get("font_pair", {})

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
    review_type: str = "brief",
    reference_domains: list[str] | None = None,
    selected_primitives: list[str] | None = None,
) -> dict:
    """Pre-build creative quality gate — a sub-agent reviews your design brief.

    TWO MODES:

    MODE 1 — GET REVIEW PROMPT (no sub_agent_verdict):
      Pass your section descriptions. Returns a critic_prompt.
      Spawn a sub-agent with this prompt — it reviews your brief as a
      fresh creative director. Don't review your own work.

    MODE 2 — RECORD VERDICT (with sub_agent_verdict):
      After your review sub-agent reports back, call again with
      sub_agent_verdict="PASS", "NEEDS WORK", or "FAIL".

    review_type options:
      "brief" — Reviews the design BRIEF before any code (default).
                Checks: Are concepts creative? Industry-native metaphors?
                Would this turn heads on Awwwards?
      "section" — Reviews individual BUILT sections against the brief.
                  Checks: Does the code match the concept? Is it ambitious?

    Flow:
      1. Call with sections=[...] → get critic_prompt
      2. Spawn sub-agent with critic_prompt
      3. If PASS → call with sub_agent_verdict="PASS" to unlock building
      4. If not PASS → revise and repeat

    Args:
        sections: Section descriptions (brief mode) or section summaries (section mode).
        sub_agent_verdict: "PASS", "NEEDS WORK", or "FAIL" from your review sub-agent.
        review_type: "brief" (pre-build) or "section" (post-build per-section).
        reference_domains: Domains from superpower_context (auto-filled if omitted).
        selected_primitives: Provider IDs (auto-filled if omitted).
    """
    prereq_error = _workflow.check_prerequisite("design_review")
    if prereq_error:
        return {"workflow_error": prereq_error}

    if not reference_domains and _workflow.context_domains:
        reference_domains = _workflow.context_domains
    if not selected_primitives and _workflow.selected_primitive_ids:
        selected_primitives = _workflow.selected_primitive_ids

    # ── MODE 2: Record verdict ──
    if sub_agent_verdict:
        verdict = sub_agent_verdict.upper().strip()
        _workflow.design_reviewed = True
        _workflow.design_review_passed = verdict == "PASS"

        if verdict == "PASS":
            return {
                "status": "DESIGN REVIEW PASSED",
                "instructions": "Your design brief passed review. Proceed to building with sub-agents.",
            }
        return {
            "status": f"DESIGN REVIEW: {verdict}",
            "instructions": (
                "Revise your section concepts based on the critic's feedback, then "
                "call superpower_design_review again with updated sections."
            ),
        }

    # ── MODE 1: Generate critic prompt ──
    section_block = ""
    for i, desc in enumerate(sections, 1):
        section_block += f"\n--- SECTION {i} ---\n{desc}\n"

    # Get industry vocabulary for the critic
    industry_vocab = ""
    if _workflow.context_domains:
        vocab = get_industry_vocab(None)  # Will be overridden below if we have intent
        industry_vocab = "\nConsider whether sections use industry-native metaphors.\n"

    if review_type == "section":
        # Post-build section review — checks code against brief
        critic_prompt = f"""You are reviewing BUILT sections against their design brief.

For each section below, evaluate:

1. **Does the code match the concept?** The brief described a specific visual metaphor. Did the builder execute it or fall back to generic patterns?

2. **Is it ambitious enough?** Would this section stand out on Awwwards? Or could any AI have produced this?

3. **Visual density** — Is every viewport filled with engaging content (photography, texture, typography at scale)? Or are there flat sections with just text on solid backgrounds?

4. **Does it feel industry-native?** The section should feel like it belongs to this specific industry, not a generic template.

Sections to review:
{section_block}

For each section, grade STRONG / ADEQUATE / NEEDS WORK / TEMPLATE-GRADE.
For anything below STRONG, give a SPECIFIC suggestion — what technique, what visual idea would fix it.

Overall verdict: PASS, NEEDS WORK, or FAIL."""

    else:
        # Brief review — pre-build creative quality check
        critic_prompt = f"""You are a ruthlessly honest creative director reviewing a design brief BEFORE any code is written.

Your job: catch boring, thin, and misguided thinking before it becomes wasted work.

The designer's planned sections:
{section_block}
{industry_vocab}

## HARD REQUIREMENTS — instant FAIL if any are violated:

1. **VOLUME**: Count the sections PER PAGE. Home page needs 10-15 sections. Every sub-page needs 8-12 sections. Total across all pages must be 30+. A page with fewer than 8 sections is UNFINISHED — this is enterprise-grade work, not a quick landing page. If the brief doesn't meet these minimums, verdict is FAIL.

2. **THEME FIT**: Is the color/mood appropriate for this business's CUSTOMERS? A community electrician's customers are homeowners — they want warmth and trust, not a dark cyberpunk dashboard. A restaurant wants warmth, not corporate blue. If the theme feels wrong for who will visit this site, verdict is FAIL.

3. **IMAGE PLAN**: Does the brief mention enough UNIQUE images? A 30+ section site needs 20-30 unique images. If the brief reuses images or doesn't plan enough variety, flag it.

## PER-SECTION EVALUATION:

For EACH section, evaluate:

1. **Does it have a CONCEPT?** Not "hero with heading and CTA" but a visual METAPHOR. A section without a concept is just layout.

2. **Would this turn heads?** If someone scrolled past this on Awwwards, would they stop?

3. **Is it structurally surprising?** Does the layout break expectations or is it predictable grids?

4. **Sensory quality** — Can you imagine the texture, depth, light? Or flat shapes on flat colors?

5. **Specificity** — Could any AI have generated this? What makes it specific to THIS brand?

Grade each section:
- **STRONG**: Distinctive creative concept, would stand out on Awwwards
- **ADEQUATE**: Competent but safe. One bolder choice would elevate it
- **NEEDS WORK**: Generic. Content without design thinking
- **TEMPLATE-GRADE**: What a free website builder produces

For sections below STRONG: say SPECIFICALLY what technique or metaphor would transform it.

Overall verdict:
- **PASS**: Meets volume minimums (30+ sections, 8+ per page), theme fits the audience, no template-grade sections, majority strong, 2+ genuinely exciting
- **NEEDS WORK**: Close but missing volume, theme is questionable, or too many adequate sections
- **FAIL**: Under volume minimums, wrong theme for audience, or most sections are generic

End your response with exactly one of: PASS, NEEDS WORK, or FAIL."""

    return {
        "critic_prompt": critic_prompt,
        "num_sections": len(sections),
        "review_type": review_type,
        "instructions": (
            "Spawn a sub-agent with the critic_prompt as its task. "
            "The sub-agent reviews your plan with fresh eyes.\n\n"
            "After it reports back:\n"
            "  - PASS → call superpower_design_review(sections=..., sub_agent_verdict='PASS')\n"
            "  - NEEDS WORK/FAIL → revise sections, call again without sub_agent_verdict"
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
def superpower_section_context(
    section_briefs: list[dict],
    include_references: bool = True,
) -> dict:
    """Get focused context for a section-builder sub-agent.

    Call this when spawning sub-agents to build specific sections. Returns a
    SHORT, focused prompt (~80 lines) with everything the sub-agent needs:
    the section concepts from your brief, font/color spec, and available packages.

    Each section_brief dict should have:
      - name: Section name (e.g. "Hero", "Features", "Team")
      - concept: The visual metaphor (e.g. "flight manifest with designation codes")
      - layout: Layout approach (e.g. "asymmetric 60/40 split")
      - interaction: Motion/interaction design (e.g. "scroll-triggered reveal with parallax")
      - mood: Emotional target (e.g. "technical precision, quiet confidence")
      - images: List of Unsplash URLs to use (optional)

    Returns a builder_prompt that you pass directly to the sub-agent.

    Args:
        section_briefs: List of section brief dicts (2-4 sections per builder)
        include_references: Whether to include reference image paths (default True)
    """
    prereq_error = _workflow.check_prerequisite("section_context")
    if prereq_error:
        return {"workflow_error": prereq_error}

    # Build the primitive toolkit string from stored state
    if _workflow.primitive_addendum:
        # Use the full addendum from context/select — it has install commands and imports
        toolkit_str = _workflow.primitive_addendum
    elif _workflow.selected_primitive_ids:
        toolkit_lines = []
        for pid in _workflow.selected_primitive_ids:
            provider = find_provider(pid)
            if provider:
                pkg = provider.get("package", "")
                name = provider.get("name", pid)
                toolkit_lines.append(f"  - {name} ({pkg})")
        toolkit_str = "\n".join(toolkit_lines)
    else:
        toolkit_str = (
            "Core toolkit: framer-motion, @tabler/icons-react, Tailwind CSS v4.\n"
            "Use 'npm install framer-motion @tabler/icons-react' as baseline."
        )

    builder_prompt = build_section_builder_prompt(
        section_briefs=section_briefs,
        font_spec=_workflow.font_pair,
        color_palette=_workflow.color_palette,
        primitive_toolkit=toolkit_str,
    )

    result: dict = {
        "builder_prompt": builder_prompt,
        "num_sections": len(section_briefs),
        "instructions": (
            "Pass the builder_prompt to a sub-agent as its task. The sub-agent "
            "builds ONLY these sections — focused work produces better results "
            "than one agent building everything."
        ),
    }

    # Include reference image paths and visual specs if available
    if include_references and _workflow.context_domains:
        result["reference_domains"] = _workflow.context_domains[:3]
        result["note"] = (
            "Share 1-2 reference images with the sub-agent (use image_path "
            "from superpower_context results) so it can see the quality bar."
        )
    if _workflow.vision_specs:
        # Give section builders the visual specs so they match the reference quality
        result["reference_visual_specs"] = _workflow.vision_specs[:2]

    return result


@mcp.tool()
def superpower_assemble_context(
    pages: list[dict],
    company_name: str = "",
) -> dict:
    """Get focused context for the assembler sub-agent.

    Call this after all section builders have delivered approved sections.
    The assembler stitches sections into a working multi-page Next.js app
    with routing, shared layout, navbar/footer, and visual consistency.

    Each page dict should have:
      - name: Page name (e.g. "Home", "About", "Services")
      - route: URL route (e.g. "/", "/about", "/services")
      - sections: List of component names in render order
                  (e.g. ["Hero", "Features", "TeamSection", "CTA"])

    Returns an assembler_prompt to pass to the assembler sub-agent.

    Args:
        pages: List of page definitions with name, route, and sections.
        company_name: The company name for navbar/branding.
    """
    prereq_error = _workflow.check_prerequisite("section_context")
    if prereq_error:
        return {"workflow_error": prereq_error}

    assembler_prompt = build_assembler_prompt(
        pages=pages,
        font_spec=_workflow.font_pair,
        color_palette=_workflow.color_palette,
        company_name=company_name,
    )

    return {
        "assembler_prompt": assembler_prompt,
        "num_pages": len(pages),
        "instructions": (
            "Pass the assembler_prompt to a sub-agent. The assembler creates "
            "the app shell: layout.tsx, page files, navbar, footer, ScrollToTop, "
            "and globals.css. It imports the already-built section components "
            "and renders them in the correct order on each page."
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

    # Build industry context for the critic
    industry_note = ""
    if _workflow.industry:
        industry_note = (
            f"\nThis is a {_workflow.industry} website. Sections should feel native to "
            f"this industry — using industry-specific metaphors and visual language, "
            f"not generic marketing patterns.\n"
        )

    critic_prompt = f"""You are a brutally honest senior design critic at a top-tier agency.

You are looking at a screenshot of a built website for "{company_name or 'a company'}".
Read the screenshot at: {screenshot_path}
{industry_note}
For EACH visible section, evaluate as a creative director:

1. **Does it have a CONCEPT?** Can you identify the visual metaphor, or is it just content in rectangles?
2. **Typography** — Are headlines massive and confident (80px+, viewport-spanning)? Or small and timid?
3. **Photography** — Does imagery dominate (60-70% of area) or is it thumbnails in cards?
4. **Surfaces** — Sharp corners (0-4px)? Texture and depth? Or rounded-xl template look?
5. **Variation** — Does each section look DIFFERENT from its neighbors? Or same pattern repeated?
6. **Density** — Every viewport filled with engaging content? Or dead space with text on flat bg?

Grade each section A-F:
- A: Portfolio-worthy. Has a distinctive creative concept. Industry-native.
- B: Good. Polished, intentional, not generic.
- C: Average. Forgettable. Could be any website.
- D: Generic cards, flat backgrounds, no design thinking.
- F: Broken or embarrassingly template-grade.

Overall verdict:
- PASS: No D/F sections, overall B or better, site feels custom-designed
- FAIL: Has D/F sections, or overall C or below, or feels like a template

For every section C or below, give SPECIFIC fixes — which CSS property, which technique,
which layout change would transform it. Not "add more richness" but WHAT specifically.

Be harsh. Honest feedback prevents mediocre output."""

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
