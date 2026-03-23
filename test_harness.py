"""Test harness for system prompt experiments.

Each test configuration generates a hero section + features section
using a specific system prompt variant, then audits the output for
quality signals.

Usage:
    python test_harness.py <config_id>

Config IDs:
    A1-A5: System prompt variations
    B1-B5: DOM on/off variations
    C1-C5: Primitive count variations
    D1-D5: Reference weight variations
    E1-E5: Instruction style variations
"""

import json
import sys
import re
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent))

from src.pipeline import (
    build_reference_surface_analysis,
    get_dom_summaries_for_domains,
)
from src.retrieval import retrieve
from src.intent import extract_intent
from src.primitives import (
    build_primitive_bundle,
    build_primitive_prompt_addendum,
    load_primitive_registry,
)


# ── System prompt variants ──────────────────────────────────────────

PROMPT_COPY_ONLY = """\
You are building a website. You have reference screenshots. COPY THEM EXACTLY.
Your output must look like it was made by the same designer.
If the references show sharp corners — use sharp corners. If light background — light.
Copy the typography, spacing, colors, and layout patterns you see.
"""

PROMPT_PRESCRIPTIVE = """\
You are building a website. Rules:
- NO rounded-xl or rounded-2xl. Use rounded-none or rounded-sm ONLY.
- NO gradient text on headings.
- NO dark bg + neon accent (the AI template look).
- NO uniform card grids. Vary every section.
- Use the npm packages from primitives, not hand-rolled CSS.
- 8+ sections, all visually different.
- Real Unsplash images.
- Hero headings: text-8xl minimum.
"""

PROMPT_HYBRID = """\
COPY the reference screenshots. They are your design spec.
Extract exact: background color, border-radius (usually SHARP 0-4px),
typography, color palette, layout patterns. Match them.

Also: NO rounded-xl. NO gradient text on full headings. NO dark+neon template.
Use npm packages from primitives. 8+ sections. Real images.
"""

PROMPT_REFERENCE_FOCUSED = """\
You have reference screenshots from award-winning websites.
Before writing ANY code:
1. Open each reference image.
2. Write down: exact background color, exact border-radius, exact font,
   exact heading size, exact color count, exact layout pattern.
3. Build a site that copies those exact parameters.

Your instincts produce generic AI output. The references produce award-winning
output. When in doubt, copy the reference.
"""

PROMPT_CURRENT = None  # Uses the live CONTEXT_SYSTEM_PROMPT


# ── Test configurations ──────────────────────────────────────────────

CONFIGS = {
    # Group A: System prompt variations
    "A1": {"prompt_variant": "copy_only", "dom": True, "prompt_text": "Light modern fintech SaaS platform"},
    "A2": {"prompt_variant": "prescriptive", "dom": True, "prompt_text": "Light modern fintech SaaS platform"},
    "A3": {"prompt_variant": "hybrid", "dom": True, "prompt_text": "Light modern fintech SaaS platform"},
    "A4": {"prompt_variant": "reference_focused", "dom": True, "prompt_text": "Light modern fintech SaaS platform"},
    "A5": {"prompt_variant": "current", "dom": True, "prompt_text": "Light modern fintech SaaS platform"},

    # Group B: DOM on/off
    "B1": {"prompt_variant": "current", "dom": True, "prompt_text": "Dark developer tools platform, Linear aesthetic"},
    "B2": {"prompt_variant": "current", "dom": False, "prompt_text": "Dark developer tools platform, Linear aesthetic"},
    "B3": {"prompt_variant": "hybrid", "dom": True, "prompt_text": "Dark developer tools platform, Linear aesthetic"},
    "B4": {"prompt_variant": "hybrid", "dom": False, "prompt_text": "Dark developer tools platform, Linear aesthetic"},
    "B5": {"prompt_variant": "reference_focused", "dom": False, "prompt_text": "Dark developer tools platform, Linear aesthetic"},

    # Group C: Different industries/styles
    "C1": {"prompt_variant": "current", "dom": True, "prompt_text": "Light sharp modern space launch company website"},
    "C2": {"prompt_variant": "current", "dom": True, "prompt_text": "Luxury fashion ecommerce, editorial, serif typography"},
    "C3": {"prompt_variant": "current", "dom": True, "prompt_text": "Clean minimal health tech platform, light theme"},
    "C4": {"prompt_variant": "current", "dom": True, "prompt_text": "Bold creative agency portfolio, experimental layout"},
    "C5": {"prompt_variant": "current", "dom": True, "prompt_text": "Enterprise compliance SaaS, trustworthy, light theme"},

    # Group D: Primitive count variations
    "D1": {"prompt_variant": "current", "dom": True, "prompt_text": "Modern SaaS marketing site", "max_primitives": 5},
    "D2": {"prompt_variant": "current", "dom": True, "prompt_text": "Modern SaaS marketing site", "max_primitives": 10},
    "D3": {"prompt_variant": "current", "dom": True, "prompt_text": "Modern SaaS marketing site", "max_primitives": 20},
    "D4": {"prompt_variant": "current", "dom": False, "prompt_text": "Modern SaaS marketing site", "max_primitives": 5},
    "D5": {"prompt_variant": "current", "dom": False, "prompt_text": "Modern SaaS marketing site", "max_primitives": 0},

    # Group E: Retrieval top_k variations
    "E1": {"prompt_variant": "current", "dom": True, "prompt_text": "Light corporate treasury platform", "top_k": 3},
    "E2": {"prompt_variant": "current", "dom": True, "prompt_text": "Light corporate treasury platform", "top_k": 5},
    "E3": {"prompt_variant": "current", "dom": True, "prompt_text": "Light corporate treasury platform", "top_k": 8},
    "E4": {"prompt_variant": "hybrid", "dom": True, "prompt_text": "Light corporate treasury platform", "top_k": 5},
    "E5": {"prompt_variant": "reference_focused", "dom": True, "prompt_text": "Light corporate treasury platform", "top_k": 5},
}

PROMPT_MAP = {
    "copy_only": PROMPT_COPY_ONLY,
    "prescriptive": PROMPT_PRESCRIPTIVE,
    "hybrid": PROMPT_HYBRID,
    "reference_focused": PROMPT_REFERENCE_FOCUSED,
    "current": PROMPT_CURRENT,
}


def run_test(config_id: str) -> dict:
    """Run a single test configuration and return results."""
    if config_id not in CONFIGS:
        return {"error": f"Unknown config: {config_id}"}

    cfg = CONFIGS[config_id]
    prompt_text = cfg["prompt_text"]
    include_dom = cfg.get("dom", True)
    top_k = cfg.get("top_k", 5)
    max_prims = cfg.get("max_primitives", None)

    # Get system prompt variant
    variant_key = cfg["prompt_variant"]
    if variant_key == "current":
        from src.pipeline import CONTEXT_SYSTEM_PROMPT
        system_prompt = CONTEXT_SYSTEM_PROMPT
    else:
        system_prompt = PROMPT_MAP[variant_key]

    # Run retrieval
    intent = extract_intent(prompt_text)
    results = retrieve(prompt_text, intent, top_k=top_k)

    # Get reference info
    domains = [r.domain for r in results]
    ref_info = []
    for r in results:
        d = r.descriptor
        ref_info.append({
            "domain": r.domain,
            "similarity": round(r.similarity, 3),
            "color_mode": d.get("color_mode"),
            "visual_style": d.get("visual_style"),
            "quality": d.get("quality_score"),
        })

    # Get DOM analysis (if enabled)
    dom_analysis = None
    surface_analysis = None
    if include_dom:
        dom_analysis = get_dom_summaries_for_domains(domains)
        surface_analysis = build_reference_surface_analysis(domains)

    # Build primitive bundle
    bundle = build_primitive_bundle(prompt_text, intent, results)
    addendum = build_primitive_prompt_addendum(bundle)

    # Count primitives
    providers = bundle.get("selected_providers", {})
    provider_ids = [p.get("id") for p in providers.values()]
    if max_prims is not None and max_prims == 0:
        provider_ids = []
        addendum = "(No primitives selected)"
    elif max_prims is not None:
        provider_ids = provider_ids[:max_prims]

    # Build full context that would be injected
    context_size = len(system_prompt) + len(addendum)
    if surface_analysis:
        context_size += len(json.dumps(surface_analysis, default=str))

    return {
        "config_id": config_id,
        "prompt_variant": variant_key,
        "prompt_text": prompt_text,
        "include_dom": include_dom,
        "top_k": top_k,
        "max_primitives": max_prims,
        "system_prompt_words": len(system_prompt.split()),
        "system_prompt_preview": system_prompt[:200],
        "context_total_chars": context_size,
        "references": ref_info,
        "reference_color_modes": [r["color_mode"] for r in ref_info],
        "reference_styles": [r["visual_style"] for r in ref_info],
        "dom_techniques": dict(surface_analysis.get("technique_frequency", {})) if surface_analysis else None,
        "design_vocabulary": surface_analysis.get("design_vocabulary", "")[:300] if surface_analysis else None,
        "primitive_count": len(provider_ids),
        "primitive_ids": provider_ids,
        "primitive_addendum_chars": len(addendum),
        "font_pair": bundle.get("font_pair", {}).get("id"),
        "archetype": bundle.get("variation_archetype", {}).get("id"),
        "motion_count": len(bundle.get("motion_primitives", [])),
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_harness.py <config_id|all>")
        print(f"Available configs: {', '.join(sorted(CONFIGS.keys()))}")
        sys.exit(1)

    config_id = sys.argv[1]

    if config_id == "all":
        results = {}
        for cid in sorted(CONFIGS.keys()):
            print(f"Running {cid}...", file=sys.stderr)
            results[cid] = run_test(cid)
        print(json.dumps(results, indent=2, default=str))
    else:
        result = run_test(config_id)
        print(json.dumps(result, indent=2, default=str))
