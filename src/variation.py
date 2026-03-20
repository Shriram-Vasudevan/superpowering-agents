"""Variation-aware reranking to reduce repetitive reference selections across runs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import settings
from src.retrieval import RetrievalResult

_MAX_MEMORY_ITEMS = 40
_MEMORY_VERSION = 1


def _memory_path() -> Path:
    return settings.reference_data_dir / "variation_memory.json"


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    return " ".join(value.strip().lower().split())


def _tokens(value: str | None) -> set[str]:
    text = _normalize_text(value)
    if not text:
        return set()
    return {part for part in text.replace("_", " ").replace("-", " ").split() if part}


def load_variation_memory() -> dict[str, Any]:
    """Load variation memory from disk, returning a safe default on errors."""
    path = _memory_path()
    if not path.exists():
        return {
            "version": _MEMORY_VERSION,
            "recent_layout_patterns": [],
            "recent_domains": [],
            "updated_at": None,
        }

    try:
        with open(path) as f:
            data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("invalid memory format")
            return {
                "version": data.get("version", _MEMORY_VERSION),
                "recent_layout_patterns": data.get("recent_layout_patterns", []),
                "recent_domains": data.get("recent_domains", []),
                "updated_at": data.get("updated_at"),
            }
    except Exception:
        return {
            "version": _MEMORY_VERSION,
            "recent_layout_patterns": [],
            "recent_domains": [],
            "updated_at": None,
        }


def save_variation_memory(memory: dict[str, Any]) -> None:
    """Persist variation memory atomically."""
    path = _memory_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    payload = {
        "version": _MEMORY_VERSION,
        "recent_layout_patterns": memory.get("recent_layout_patterns", [])[:_MAX_MEMORY_ITEMS],
        "recent_domains": memory.get("recent_domains", [])[:_MAX_MEMORY_ITEMS],
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }

    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w") as f:
        json.dump(payload, f, indent=2)
    tmp_path.replace(path)


def _archetype_match_score(result: RetrievalResult, archetype: dict[str, Any]) -> float:
    """Score how well a result matches the requested variation archetype."""
    if not archetype:
        return 0.0

    result_tokens = set()
    desc = result.descriptor
    for key in ("layout_pattern", "visual_style", "typography_style", "distinguishing_features"):
        result_tokens.update(_tokens(str(desc.get(key, ""))))

    archetype_tokens = set()
    for key in ("layout", "hero", "section_rhythm", "background"):
        archetype_tokens.update(_tokens(str(archetype.get(key, ""))))

    if not archetype_tokens:
        return 0.0

    overlap = len(result_tokens & archetype_tokens)
    return overlap / max(len(archetype_tokens), 1)


def _novelty_score(result: RetrievalResult, memory: dict[str, Any]) -> float:
    """Reward unseen patterns and penalize recently repeated ones."""
    recent_layouts = {_normalize_text(x) for x in memory.get("recent_layout_patterns", [])}
    recent_domains = {_normalize_text(x) for x in memory.get("recent_domains", [])}

    layout = _normalize_text(str(result.descriptor.get("layout_pattern", "")))
    domain = _normalize_text(result.domain)

    score = 0.0
    if layout and layout not in recent_layouts:
        score += 0.35
    elif layout:
        score -= 0.65

    if domain and domain in recent_domains:
        score -= 1.0

    return score


def rerank_for_variation(
    results: list[RetrievalResult],
    archetype: dict[str, Any],
    memory: dict[str, Any] | None = None,
) -> list[RetrievalResult]:
    """Rerank references with archetype alignment, novelty, and diversity ordering."""
    if len(results) <= 1:
        return results

    state = memory or load_variation_memory()
    base_scores: dict[str, float] = {}

    def score(result: RetrievalResult) -> float:
        base = result.similarity
        archetype_bonus = _archetype_match_score(result, archetype) * 0.9
        novelty = _novelty_score(result, state)
        total = base + archetype_bonus + novelty
        return total

    for result in results:
        base_scores[result.domain] = score(result)

    # Greedy diversity selection: avoid repeating same layout/style in sequence.
    remaining = list(results)
    selected: list[RetrievalResult] = []

    while remaining:
        if not selected:
            best = max(remaining, key=lambda r: (base_scores.get(r.domain, 0.0), r.domain))
            selected.append(best)
            remaining.remove(best)
            continue

        def candidate_score(candidate: RetrievalResult) -> tuple[float, str]:
            layout = _normalize_text(str(candidate.descriptor.get("layout_pattern", "")))
            style = _normalize_text(str(candidate.descriptor.get("visual_style", "")))

            layout_repeats = 0
            style_repeats = 0
            for picked in selected:
                if layout and layout == _normalize_text(str(picked.descriptor.get("layout_pattern", ""))):
                    layout_repeats += 1
                if style and style == _normalize_text(str(picked.descriptor.get("visual_style", ""))):
                    style_repeats += 1

            penalty = (layout_repeats * 0.35) + (style_repeats * 0.2)
            total = base_scores.get(candidate.domain, 0.0) - penalty
            return total, candidate.domain

        best = max(remaining, key=candidate_score)
        selected.append(best)
        remaining.remove(best)

    return selected


def record_reference_usage(results: list[RetrievalResult], top_n: int = 3) -> None:
    """Record top references to memory to discourage immediate repetition."""
    if not results:
        return

    memory = load_variation_memory()
    recent_layouts = [_normalize_text(x) for x in memory.get("recent_layout_patterns", [])]
    recent_domains = [_normalize_text(x) for x in memory.get("recent_domains", [])]

    for result in results[:top_n]:
        layout = _normalize_text(str(result.descriptor.get("layout_pattern", "")))
        domain = _normalize_text(result.domain)

        if layout:
            recent_layouts.insert(0, layout)
        if domain:
            recent_domains.insert(0, domain)

    # De-duplicate while preserving recency
    dedup_layouts: list[str] = []
    for item in recent_layouts:
        if item and item not in dedup_layouts:
            dedup_layouts.append(item)

    dedup_domains: list[str] = []
    for item in recent_domains:
        if item and item not in dedup_domains:
            dedup_domains.append(item)

    memory["recent_layout_patterns"] = dedup_layouts[:_MAX_MEMORY_ITEMS]
    memory["recent_domains"] = dedup_domains[:_MAX_MEMORY_ITEMS]
    save_variation_memory(memory)
