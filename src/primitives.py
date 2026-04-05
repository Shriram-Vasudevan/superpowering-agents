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
    """Score a provider against inferred tags.

    Normalizes the base score to a 0-1 range so tag matches have real impact.
    A provider with 3 tag matches beats one with a slightly higher base score.
    """
    raw_base = float(provider.get("score", 0))
    # Normalize: compress the 7.0-9.7 range into 0-1 so tags dominate
    base = max(0.0, (raw_base - 7.0) / 3.0)  # 7.0→0.0, 8.5→0.5, 10.0→1.0
    gains = 0.0
    for item in provider.get("when_to_use", []):
        if item == "default":
            gains += 0.1  # "default" is weak signal, not a real match
        elif _safe_slug(item) in tags:
            gains += 1.0
    penalties = 0.0
    for item in provider.get("avoid_when", []):
        if _safe_slug(item) in tags:
            penalties += 1.5
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
    """Pick a variation archetype by semantic tag matching, with hash tiebreaker.

    Scores each archetype against the inferred tags. If two archetypes tie,
    uses SHA-256 hash of the prompt to break the tie deterministically.
    """
    archetypes = registry.get("variation_archetypes", [])
    if not archetypes:
        return {}

    # Build a scoring function from archetype metadata
    def _archetype_score(arch: dict[str, Any]) -> float:
        score = 0.0
        arch_id = _safe_slug(arch.get("id", ""))
        # Match archetype id parts against tags
        for part in arch_id.split("-"):
            if part in tags:
                score += 2.0
        # Tokenize description into words for matching (handle commas, periods)
        raw_desc = arch.get("description", "").lower()
        desc_words = set(
            w.strip(".,;:()") for w in raw_desc.replace("/", " ").replace("-", " ").split()
        )
        for tag in tags:
            if tag != "default" and tag in desc_words:
                score += 1.5
        # Match signature_moves — bonus if tags overlap
        for move in arch.get("signature_moves", []):
            if _safe_slug(move) in tags:
                score += 0.5
        return score

    # Score all archetypes
    scored = [(a, _archetype_score(a)) for a in archetypes]
    best_score = max(s for _, s in scored)

    # Among the best-scoring, use hash to pick deterministically
    top_archetypes = [a for a, s in scored if s >= best_score - 0.5]
    if len(top_archetypes) == 1:
        return top_archetypes[0]

    seed_input = prompt + "|" + "|".join(r.domain for r in results[:5]) + "|" + "|".join(sorted(tags))
    digest = hashlib.sha256(seed_input.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(top_archetypes)
    return top_archetypes[idx]


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
    """Render injectable system-prompt addendum from a primitive bundle.

    Presents primitives as a toolkit (what's available, how to import) rather
    than a mandatory checklist. The creative brief determines which primitives
    serve each section — not every primitive needs to appear.
    """
    lines: list[str] = []
    lines.append("## PRIMITIVE TOOLKIT")
    lines.append(
        "These packages are available for this project. Use the ones that serve "
        "your design concepts. Not every package needs to appear — pick what fits "
        "each section's concept. But DO use the actual packages rather than writing "
        "lesser CSS equivalents."
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
        for p in pkg.replace(" OR ", "|").replace(" + ", "|").split("|"):
            p = p.strip()
            if p and p.lower() not in _skip_packages and p not in seen_packages and not p.startswith("@radix"):
                seen_packages.add(p)
                installable_packages.append(p)
                if p in _import_map:
                    import_lines.append(_import_map[p])

    if "framer-motion" not in seen_packages:
        installable_packages.insert(0, "framer-motion")
        import_lines.insert(0, _import_map["framer-motion"])
        seen_packages.add("framer-motion")

    if installable_packages:
        lines.append(f"\n### Install (run before writing code):")
        lines.append(f"npm install {' '.join(installable_packages)}")
        lines.append("")
        lines.append("### Imports:")
        lines.extend(import_lines)
        lines.append("")

    # List available providers by category
    lines.append("### Available packages by category:")
    for category in _ALL_PROVIDER_CATEGORIES:
        provider = providers.get(category)
        if provider:
            lines.extend(_provider_lines(category, provider))

    # Font pair
    font_pair = bundle.get("font_pair") or {}
    if font_pair:
        display_font = font_pair.get('display', 'Inter')
        body_font = font_pair.get('body', 'Inter')
        note = font_pair.get("usage_note", "")
        display_import = display_font.replace(' ', '_')
        body_import = body_font.replace(' ', '_')
        lines.append(
            f"\n### Font pairing: {display_font} (display) + {body_font} (body)"
            + (f" — {note}" if note else "")
        )
        lines.append(
            f"  import {{ {display_import}, {body_import} }} from 'next/font/google'"
        )

    # Archetype as inspiration
    archetype = bundle.get("variation_archetype") or {}
    if archetype:
        lines.append(f"\n### Design archetype (inspiration, not blueprint): {archetype.get('id', 'N/A')}")
        lines.append(f"  Layout: {archetype.get('layout', 'N/A')}")
        lines.append(f"  Hero approach: {archetype.get('hero', 'N/A')}")
        lines.append(f"  Section rhythm: {archetype.get('section_rhythm', 'N/A')}")
        lines.append(f"  Background: {archetype.get('background', 'N/A')}")
        moves = archetype.get("signature_moves", [])
        if moves:
            lines.append(f"  Signature moves to consider: {', '.join(moves)}")

    # Motion primitives as suggestions
    motion = bundle.get("motion_primitives", [])
    if motion:
        lines.append(
            "\n### Suggested animations (every section should have motion — "
            "pick what serves each concept):"
        )
        for item in motion:
            lines.append(f"  - {item.get('id')}: {item.get('description')}")

    # Patterns that award-winning sites avoid (identity-based, not ban-list)
    lines.append(
        "\n### What award-winning sites never do:"
        "\n  Award-winning sites avoid same-sized card grids repeated across sections,"
        "\n  generic heroes (just a headline + subheadline + button on flat background),"
        "\n  icon grids where every icon sits in an identical rounded rectangle,"
        "\n  raw CSS linear-gradients without texture or filtering,"
        "\n  content pushed to the bottom of full-viewport sections,"
        "\n  the same background approach on adjacent sections,"
        "\n  and any section that is just text on a flat solid color."
        "\n  If you catch yourself doing any of these — stop and redesign."
    )

    return "\n".join(lines)
