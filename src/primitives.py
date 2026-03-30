"""Primitive orchestration layer: registry loading, provider selection, and prompt addendum."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from typing import Any

from src.config import settings
from src.intent import UserIntent
from src.retrieval import RetrievalResult


def list_providers(category: str | None = None) -> list[dict[str, Any]]:
    """Return providers from registry, optionally filtered by category."""
    providers = load_primitive_registry().get("providers", [])
    if not category:
        return providers
    return [p for p in providers if p.get("category") == category]


def find_provider(provider_id: str) -> dict[str, Any] | None:
    """Find a provider by stable id."""
    for provider in load_primitive_registry().get("providers", []):
        if provider.get("id") == provider_id:
            return provider
    return None


def find_font_pair(font_pair_id: str) -> dict[str, Any] | None:
    """Find a font pair by id."""
    for pair in load_primitive_registry().get("font_pairs", []):
        if pair.get("id") == font_pair_id:
            return pair
    return None


def find_motion_primitive(motion_id: str) -> dict[str, Any] | None:
    """Find a motion primitive by id."""
    for motion in load_primitive_registry().get("motion_primitives", []):
        if motion.get("id") == motion_id:
            return motion
    return None


def find_archetype(archetype_id: str) -> dict[str, Any] | None:
    """Find a variation archetype by id."""
    for archetype in load_primitive_registry().get("variation_archetypes", []):
        if archetype.get("id") == archetype_id:
            return archetype
    return None


def build_manual_primitive_bundle(
    provider_ids: list[str],
    font_pair_id: str | None = None,
    motion_ids: list[str] | None = None,
    archetype_id: str | None = None,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    """Build a primitive bundle from explicit user/LLM selections."""
    registry = load_primitive_registry()
    selected_providers: dict[str, dict[str, Any]] = {}

    for provider_id in provider_ids:
        provider = find_provider(provider_id)
        if not provider:
            continue
        category = provider.get("category", "unknown")
        selected_providers[category] = provider

    font_pair = find_font_pair(font_pair_id) if font_pair_id else {}

    motion_primitives: list[dict[str, Any]] = []
    for motion_id in motion_ids or []:
        motion = find_motion_primitive(motion_id)
        if motion:
            motion_primitives.append(motion)

    variation_archetype = find_archetype(archetype_id) if archetype_id else {}

    return {
        "version": registry.get("version"),
        "tags": sorted(set(tags or [])),
        "selected_providers": selected_providers,
        "font_pair": font_pair or {},
        "motion_primitives": motion_primitives,
        "variation_archetype": variation_archetype or {},
        "banned_patterns": registry.get("banned_patterns", []),
        "critique_rubric": registry.get("critique_rubric", []),
        "policy": registry.get("default_policy", {}),
    }



@lru_cache(maxsize=1)
def load_primitive_registry() -> dict[str, Any]:
    """Load and cache primitive registry data."""
    path = settings.reference_data_dir / "primitive_registry.json"
    with open(path) as f:
        return json.load(f)


def _safe_slug(value: str) -> str:
    return value.lower().replace(" ", "-").replace("/", "-")


def infer_design_tags(intent: UserIntent, results: list[RetrievalResult]) -> set[str]:
    """Infer tags from user intent and top references for primitive selection."""
    tags: set[str] = {"default"}

    if intent.industry:
        tags.add(intent.industry)
        tags.add(_safe_slug(intent.industry))

    if intent.page_type:
        tags.add(intent.page_type)
        tags.add(_safe_slug(intent.page_type))

    if intent.style_keywords:
        tags.update(_safe_slug(k) for k in intent.style_keywords)

    if intent.color_preference == "dark":
        tags.add("moody")

    for result in results[:3]:
        desc = result.descriptor
        for key in ("visual_style", "layout_pattern", "typography_style", "industry"):
            raw = desc.get(key)
            if isinstance(raw, str) and raw.strip():
                tags.update(_safe_slug(part.strip()) for part in raw.split(",") if part.strip())

    return tags


def _score_provider(provider: dict[str, Any], tags: set[str]) -> float:
    base = float(provider.get("score", 0))
    gains = 0.0
    for item in provider.get("when_to_use", []):
        if _safe_slug(item) in tags:
            gains += 1.0
    penalties = 0.0
    for item in provider.get("avoid_when", []):
        if _safe_slug(item) in tags:
            penalties += 2.0
    return base + gains - penalties


_ALWAYS_INCLUDE_CATEGORIES = frozenset({
    "icons", "animation", "scroll", "fonts", "images", "image-optimization",
    "buttons", "layout", "surface", "background", "image-effects",
    "text-effects", "marquee", "theming",
})
"""Categories that are relevant to virtually every marketing site."""


def select_providers(tags: set[str], registry: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Pick best provider per RELEVANT category using weighted tags.

    Only includes a category if:
    - It's in the always-include set (core visual categories), OR
    - The best provider in that category has at least one tag match
      (meaning the site actually needs that kind of primitive)
    """
    selected: dict[str, dict[str, Any]] = {}

    by_category: dict[str, list[dict[str, Any]]] = {}
    for provider in registry.get("providers", []):
        by_category.setdefault(provider.get("category", "unknown"), []).append(provider)

    for category, providers in by_category.items():
        ranked = sorted(providers, key=lambda p: _score_provider(p, tags), reverse=True)
        if not ranked:
            continue
        best = ranked[0]

        # Always include core visual categories
        if category in _ALWAYS_INCLUDE_CATEGORIES:
            selected[category] = best
            continue

        # For optional categories, only include if the best provider
        # has at least one tag match (score > base score)
        base = float(best.get("score", 0))
        actual = _score_provider(best, tags)
        if actual > base:  # Has at least one tag match
            selected[category] = best

    return selected


def choose_font_pair(tags: set[str], registry: dict[str, Any]) -> dict[str, Any]:
    """Select a font pair that best matches inferred tone tags."""
    pairs = registry.get("font_pairs", [])
    if not pairs:
        return {}

    # Don't let 'default' bias font selection — it matches everything
    font_tags = tags - {"default"}

    def pair_score(pair: dict[str, Any]) -> float:
        score = 0.0
        for tone in pair.get("tone", []):
            if tone == "default":
                continue  # Skip 'default' tone — it's not a real signal
            if _safe_slug(tone) in font_tags:
                score += 1.0
        if "editorial" in tags and pair.get("contrast") == "high":
            score += 0.5
        return score

    ranked = sorted(pairs, key=pair_score, reverse=True)
    return ranked[0]


def choose_archetype(
    prompt: str,
    tags: set[str],
    results: list[RetrievalResult],
    registry: dict[str, Any],
) -> dict[str, Any]:
    """Deterministically pick one variation archetype for the request."""
    archetypes = registry.get("variation_archetypes", [])
    if not archetypes:
        return {}

    seed_input = prompt + "|" + "|".join(r.domain for r in results[:5]) + "|" + "|".join(sorted(tags))
    digest = hashlib.sha256(seed_input.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(archetypes)
    return archetypes[idx]


def choose_motion_primitives(tags: set[str], registry: dict[str, Any]) -> list[dict[str, Any]]:
    """Pick a motion set: one entrance, one hover, one scroll, plus tag-specific additions."""
    motions = registry.get("motion_primitives", [])
    if not motions:
        return []

    by_type: dict[str, list[dict[str, Any]]] = {}
    for m in motions:
        by_type.setdefault(m.get("type", "other"), []).append(m)

    selected: list[dict[str, Any]] = []

    # Always: one entrance — prefer text-reveal-clip for editorial, blur-scale-in for luxury, default fade-up
    entrance_id = "fade-up-stagger"
    if any(t in tags for t in ("editorial", "brutalist", "magazine")):
        entrance_id = "text-reveal-clip"
    elif any(t in tags for t in ("luxury", "soft-luxury", "premium")):
        entrance_id = "blur-scale-in"
    for m in by_type.get("entrance", []):
        if m.get("id") == entrance_id:
            selected.append(m)
            break
    if not selected:
        selected.extend(by_type.get("entrance", [])[:1])

    # Always: one hover
    hover_id = "scale-fade"
    if any(t in tags for t in ("interactive", "animated", "saas", "marketing")):
        hover_id = "magnetic-cursor-pull"
    for m in by_type.get("hover", []):
        if m.get("id") == hover_id:
            selected.append(m)
            break
    if len(selected) < 2:
        selected.extend(by_type.get("hover", [])[:1])

    # Always: one scroll parallax
    scroll_id = "parallax-image-drift"
    for m in by_type.get("scroll", []):
        if m.get("id") == scroll_id:
            selected.append(m)
            break
    if len(selected) < 3:
        selected.extend(by_type.get("scroll", [])[:1])

    # Stats sections → counter
    if any(t in tags for t in ("statistics", "metrics", "saas", "marketing", "startup")):
        for m in by_type.get("scroll", []):
            if m.get("id") == "counter-up-on-scroll" and m not in selected:
                selected.append(m)
                break

    # Grid layouts → cascade
    if any(t in tags for t in ("grid", "bento", "gallery", "portfolio", "features")):
        for m in by_type.get("entrance", []):
            if m.get("id") == "stagger-grid-cascade" and m not in selected:
                selected.append(m)
                break

    # Ambient grain for moody/editorial/retro/film/luxury
    if any(t in tags for t in ("editorial", "moody", "retro", "film", "luxury", "dark-cinematic", "dark")):
        for m in by_type.get("ambient", []):
            if m not in selected:
                selected.append(m)
                break

    # Mobile/drawer contexts → drawer-scale-background overlay motion
    if any(t in tags for t in ("mobile-first", "native-feel", "bottom-sheet", "filters")):
        for m in by_type.get("overlay", []):
            if m not in selected:
                selected.append(m)
                break

    # Success-state / onboarding contexts → confetti burst
    if any(t in tags for t in ("success-states", "onboarding", "saas", "purchase")):
        for m in by_type.get("delight", []):
            if m not in selected:
                selected.append(m)
                break

    # Data-fetching / dashboard contexts → skeleton shimmer transition
    if any(t in tags for t in ("dashboard", "data-heavy", "data-fetching", "analytics", "saas-metrics")):
        for m in by_type.get("loading", []):
            if m not in selected:
                selected.append(m)
                break

    return selected


def build_primitive_bundle(
    prompt: str,
    intent: UserIntent,
    results: list[RetrievalResult],
) -> dict[str, Any]:
    """Build complete primitive recommendation payload for a request."""
    registry = load_primitive_registry()
    tags = infer_design_tags(intent, results)

    providers = select_providers(tags, registry)
    font_pair = choose_font_pair(tags, registry)
    archetype = choose_archetype(prompt, tags, results, registry)
    motion_set = choose_motion_primitives(tags, registry)

    return {
        "version": registry.get("version"),
        "tags": sorted(tags),
        "selected_providers": providers,
        "font_pair": font_pair,
        "motion_primitives": motion_set,
        "variation_archetype": archetype,
        "banned_patterns": registry.get("banned_patterns", []),
        "critique_rubric": registry.get("critique_rubric", []),
        "policy": registry.get("default_policy", {}),
    }


# Categories that experienced devs rarely reach for by default but that produce
# the most visible differentiation. These are surfaced prominently in the catalog.
_DISCOVERY_CATEGORIES = frozenset({
    "text-effects",
    "background",
    "image-effects",
    "surface",
    "compositing",
    "marquee",
    "delight",
    "loading",
    "command-palette",
    "css-animation",
    "diagrams",
})


def get_discovery_highlights(registry: dict) -> list[dict]:
    """Return providers from discovery-tier categories (lean format).

    These are surfaced separately from the full catalog so the model encounters
    the less-obvious options first, before pattern-matching to its defaults.
    """
    providers = registry.get("providers", [])
    highlights = []
    for p in providers:
        if p.get("category") in _DISCOVERY_CATEGORIES:
            highlights.append({
                "id": p.get("id"),
                "category": p.get("category"),
                "name": p.get("name"),
                "package": p.get("package", ""),
            })
    return highlights


_ALL_PROVIDER_CATEGORIES = (
    "headless-ui", "icons", "animation", "css-animation", "scroll", "fonts",
    "images", "image-optimization", "image-effects", "buttons",
    "layout", "surface", "text-effects", "background", "compositing", "marquee",
    "data-display", "charts", "data-table", "diagrams", "carousel", "loading",
    "code", "delight", "forms", "positioning", "3d", "theming", "overlay",
    "command-palette", "feedback", "reference",
)


def _provider_lines(category: str, provider: dict[str, Any]) -> list[str]:
    name = provider.get("name", "unknown")
    package = provider.get("package", "")
    lines = [f"- [{category}] {name} ({package})"]
    variants = provider.get("variants")
    if variants and isinstance(variants, dict):
        for key, val in variants.items():
            if key == "usage_rule" or key == "usage_note" or key == "implementation" or key == "combination_note" or key == "stacking_note" or key == "alternate_direction":
                lines.append(f"    note: {val}")
            elif isinstance(val, list):
                lines.append(f"    {key}: {', '.join(str(v) for v in val)}")
            elif isinstance(val, dict):
                inner = ", ".join(f"{k}:{v}" for k, v in val.items())
                lines.append(f"    {key}: {inner}")
    return lines


def build_primitive_prompt_addendum(bundle: dict[str, Any]) -> str:
    """Render injectable system-prompt addendum from a primitive bundle."""
    lines: list[str] = []
    lines.append("## Your Primitive Toolkit")
    lines.append(
        "These are the primitives selected for this site. Use them thoughtfully — "
        "each one should serve your design personality. Not every primitive needs to "
        "appear on every page. Focus on the 5-6 that make THIS site's personality "
        "come alive. A compliance site uses different primitives than a dev tools site. "
        "Think: what does this specific brand need?"
    )

    # Generate ready-to-paste npm install command and import statements
    providers = bundle.get("selected_providers", {})
    installable_packages: list[str] = []
    import_lines: list[str] = []
    _skip_packages = {"native-css", "native-svg", "native", "native-css-grid",
                      "native + framer-motion", "native-css + framer-motion",
                      "framer-motion or native", "pattern-reference", "http api",
                      "tailwind", "next"}
    _import_map = {
        "framer-motion": 'import { motion, useInView, useScroll, useTransform, AnimatePresence } from "framer-motion"',
        "@tabler/icons-react": 'import { IconArrowRight, IconCheck } from "@tabler/icons-react"',
        "class-variance-authority": 'import { cva, type VariantProps } from "class-variance-authority"',
        "react-parallax-tilt": 'import Tilt from "react-parallax-tilt"',
        "react-countup": 'import CountUp from "react-countup"',
        "react-type-animation": 'import { TypeAnimation } from "react-type-animation"',
        "recharts": 'import { AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer } from "recharts"',
        "@paper-design/shaders-react": 'import { GrainGradient, MeshGradient } from "@paper-design/shaders-react"',
        "lenis": 'import Lenis from "lenis"',
        "react-awesome-reveal": 'import { Fade, Slide } from "react-awesome-reveal"',
        "split-type": 'import SplitType from "split-type"',
        "@formkit/auto-animate": 'import { useAutoAnimate } from "@formkit/auto-animate/react"',
        "react-progressive-blur": 'import { ProgressiveBlur } from "react-progressive-blur"',
        "sonner": 'import { toast } from "sonner"',
        "react-fast-marquee": 'import Marquee from "react-fast-marquee"',
        "shiki": '// Use shiki for syntax highlighting (see shiki docs for setup)',
        "@nivo/core": 'import { ResponsiveLine } from "@nivo/line"',
        "react-loading-skeleton": 'import Skeleton from "react-loading-skeleton"',
    }

    seen_packages: set[str] = set()
    for provider in providers.values():
        pkg = provider.get("package", "")
        # Handle composite packages like "@paper-design/shaders-react OR native-css"
        # and "react-hook-form + zod + @hookform/resolvers"
        for p in pkg.replace(" OR ", "|").replace(" + ", "|").split("|"):
            p = p.strip()
            if p and p.lower() not in _skip_packages and p not in seen_packages and not p.startswith("@radix"):
                seen_packages.add(p)
                installable_packages.append(p)
                if p in _import_map:
                    import_lines.append(_import_map[p])

    # Also add framer-motion always (core requirement)
    if "framer-motion" not in seen_packages:
        installable_packages.insert(0, "framer-motion")
        import_lines.insert(0, _import_map["framer-motion"])
        seen_packages.add("framer-motion")

    if installable_packages:
        lines.append(f"\n## INSTALL COMMAND — run this FIRST, before writing any code:")
        lines.append(f"npm install {' '.join(installable_packages)}")
        lines.append("")
        lines.append("## IMPORT STATEMENTS — copy these into your components:")
        lines.extend(import_lines)
        lines.append("")
    for category in _ALL_PROVIDER_CATEGORIES:
        provider = providers.get(category)
        if provider:
            lines.extend(_provider_lines(category, provider))

    font_pair = bundle.get("font_pair") or {}
    if font_pair:
        display_font = font_pair.get('display', 'Inter')
        body_font = font_pair.get('body', 'Inter')
        note = font_pair.get("usage_note", "")
        # Generate the exact next/font/google import
        display_import = display_font.replace(' ', '_')
        body_import = body_font.replace(' ', '_')
        lines.append(
            f"- [fonts] MANDATORY: {display_font} (display) + {body_font} (body)"
            + (f" — {note}" if note else "")
        )
        lines.append(
            f"  Import: import {{ {display_import}, {body_import} }} from 'next/font/google'"
        )

    archetype = bundle.get("variation_archetype") or {}
    if archetype:
        lines.append("\n## Design Archetype — Use as inspiration, not a rigid blueprint:")
        lines.append(f"  archetype: {archetype.get('id', 'N/A')}")
        lines.append(f"  layout style: {archetype.get('layout', 'N/A')}")
        lines.append(f"  hero type: {archetype.get('hero', 'N/A')}")
        lines.append(f"  section rhythm: {archetype.get('section_rhythm', 'N/A')}")
        lines.append(f"  background treatment: {archetype.get('background', 'N/A')}")
        moves = archetype.get("signature_moves", [])
        if moves:
            lines.append(f"  signature moves (incorporate these): {', '.join(moves)}")
        lines.append("  NOTE: This archetype is a STARTING POINT. Adapt it to serve the")
        lines.append("  industry and brand. Invent your own structural ideas beyond this.")

    motion = bundle.get("motion_primitives", [])
    if motion:
        lines.append(
            "\n## MANDATORY Motion Primitives — every one of these MUST be implemented. "
            "No static sections. No missing hover states. Implement ALL:"
        )
        for item in motion:
            lines.append(f"  - {item.get('id')}: {item.get('description')}")

    banned = bundle.get("banned_patterns", [])
    if banned:
        lines.append("\n## BANNED PATTERNS — using any of these is instant failure:")
        for pattern in banned:
            lines.append(f"  ✗ {pattern}")

    rubric = bundle.get("critique_rubric", [])
    if rubric:
        lines.append("\n## Pre-output self-critique checklist (ALL must pass):")
        for item in rubric:
            lines.append(f"  [ ] {item}")

    lines.append(
        "\n## MANDATORY WORKFLOW — follow EVERY step. Skipping ANY = failure.\n\n"
        "  STEP 1. Study reference images with Read tool. Extract exact visual parameters.\n"
        "  STEP 2. Study reference_visual_specs. These are your design spec.\n"
        "  STEP 3. Run the npm install command above.\n"
        "  STEP 4. Call superpower_images 3+ times for real Unsplash photos.\n"
        "  STEP 5. BEFORE BUILDING — call superpower_design_review with a description\n"
        "          of every planned section. If it returns FAIL — revise your plan.\n"
        "          Do NOT start writing code until design review PASSES.\n"
        "          Use ToolSearch to fetch the tool schema if needed.\n"
        "  STEP 6. Build the full site. Take your time. Quality > speed. If building\n"
        "          takes 30 minutes, that's fine. Rushing produces generic output.\n"
        "  STEP 7. After building, start dev server. Call superpower_review_build\n"
        "          on the homepage URL. This tool enforces an ITERATION LOOP:\n"
        "          - It screenshots the page and grades EVERY section (A-F)\n"
        "          - If review_status is 'FAILED — MUST ITERATE', you MUST:\n"
        "            a) Fix ALL critical_issues and D/F sections using the specific fixes provided\n"
        "            b) Rebuild the page\n"
        "            c) Call superpower_review_build AGAIN on the same URL\n"
        "            d) Repeat until review_status is 'PASSED'\n"
        "          - DO NOT skip this loop. DO NOT declare complete while review is failing.\n"
        "          - Expect 2-3 iterations. This is where quality happens.\n"
        "          Use ToolSearch to fetch the tool schema if needed.\n"
        "  STEP 8. Call superpower_check_layout on every page for structural issues.\n"
        "  STEP 9. Call superpower_review_build on EVERY subpage too (/pricing, /about, etc).\n"
        "          Run the same iteration loop on each — fix D/F sections, re-review.\n"
        "  STEP 10. Verify every selected primitive is actually imported and used.\n"
        "  STEP 11. Only THEN declare complete. The site is NOT done until ALL pages\n"
        "           have passed superpower_review_build with grade B+ and no D/F sections.\n\n"

        "## BUILD REQUIREMENTS\n\n"

        "  PAGES: Multiple pages that make sense for THIS business. NOT a rigid\n"
        "     template of 'home + pricing + about.' An aerospace company needs\n"
        "     vehicles, missions, facilities. A restaurant needs menu, reservations.\n"
        "     A law firm needs practice areas, cases, team. Choose pages that FIT\n"
        "     the industry. Home page should have 8+ visually distinct sections.\n"
        "     7 powerful sections > 12 mediocre ones.\n\n"

        "  FOLDER: name after company (lowercase). 'my-app' = failure.\n\n"

        "  DESIGN LANGUAGE: The ENTIRE site — navigation, section transitions,\n"
        "     micro-copy, metadata, footer — should feel NATIVE to the industry.\n"
        "     An aerospace site should feel like mission control. A law firm should\n"
        "     feel like a legal brief. Do NOT use the same navbar/footer/hero pattern\n"
        "     on every site. INVENT navigation and structure that serves THIS brand.\n\n"

        "  PHOTOGRAPHY: Images should DOMINATE — 60-70% of visual area in key\n"
        "     sections, not thumbnails in card grids. Use url_full for heroes.\n"
        "     Dark overlays must stay below 40% opacity so images remain visible.\n\n"

        "  TYPOGRAPHY: Hero headings should be MASSIVE — viewport-spanning when\n"
        "     possible. Use the full width. Think text-[10vw] or text-[12vw], not\n"
        "     text-5xl centered in a narrow column. Mixed weights (thin + black)\n"
        "     in the same heading creates editorial sophistication.\n\n"

        "  VISUAL DENSITY: Every viewport should reward the user — a new image,\n"
        "     texture, or typographic moment. No section is just text on flat color.\n\n"

        "  CORNERS: Prefer sharp corners (0-4px). NO rounded-xl or rounded-2xl.\n\n"

        "  BRAND: Bold text only for company name. No icon logos.\n\n"

        "  DESIGN CONFIDENCE:\n"
        "     - Features are a STORY, not a grid. Each should transform the visual.\n"
        "     - Every page hero must feel COMPLETELY DIFFERENT from every other.\n"
        "     - Track background treatment usage: never repeat the same treatment\n"
        "       twice on the same page.\n\n"

        "  TECH: Tailwind v4 — @theme inline { } for custom colors, NOT :root.\n"
        "     Node.js 25 — add NODE_OPTIONS='--localstorage-file=/tmp/nextls' to scripts.\n\n"

        "  SCROLL RESET: MANDATORY for multi-page sites. Add a ScrollToTop component\n"
        "     that uses usePathname() to detect route changes and scrolls to top.\n"
        "     If using Lenis, call lenis.scrollTo(0, { immediate: true }).\n"
        "     Without this, users arrive at the MIDDLE of new pages — a critical UX bug.\n\n"

        "  VISUAL AMBITION: Every section must have a creative IDEA, not just content\n"
        "     in boxes. Ask: would someone screenshot this? If you find yourself making\n"
        "     uniform cards with icons, stop and think about what would make this section\n"
        "     genuinely surprising. The design_review and review_build tools will reject\n"
        "     safe, template-grade work.\n\n"

        "## QUALITY CHECK — verify before finishing\n"
        "  • Does the site feel CUSTOM and INDUSTRY-NATIVE, not like a swapped template?\n"
        "  • Is there a coherent design language throughout (not just sections stitched together)?\n"
        "  • Is photography PROMINENT — large, full-bleed, dominant in key sections?\n"
        "  • Are hero headings MASSIVE — viewport-spanning, not small centered text?\n"
        "  • Does the navigation feel invented for THIS brand, not generic?\n"
        "  • npx next build succeeds with zero errors\n"
        "  • Real Unsplash images in every image slot\n"
        "  • Brand name is text only — no icon logos\n"
        "  • No two page heroes look the same\n"
        "  • Hero and CTA content is vertically centered, not pushed to bottom\n"
        "  • No section is just text on flat solid background\n"
        "  • ScrollToTop component exists and resets scroll on route change\n"
        "  • At least 3 ambitious techniques used (glass, shaders, tilt, clip-path, etc.)\n"
        "  • superpower_review_build PASSED on every page (grade B+, no D/F sections)\n"
        "If any fails — go back and fix it. Do not declare complete."
    )

    return "\n".join(lines)
