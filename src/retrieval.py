"""Two-stage retrieval: metadata filter + CLIP vector search with composite scoring."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
from transformers import CLIPModel, CLIPProcessor

from src.config import settings
from src.intent import UserIntent
from src.utils import domain_to_screenshot_path


@dataclass
class RetrievalResult:
    domain: str
    cluster_id: int
    row_idx: int
    similarity: float
    descriptor: dict[str, Any]
    screenshot_path: Path


# Descriptor fields to include in RetrievalResult
DESCRIPTOR_FIELDS = (
    "page_type", "visual_style", "quality_score", "industry",
    "industry_confidence", "business_model", "brand_tier", "industry_style_profile",
    "color_mode", "layout_pattern", "typography_style", "design_era",
    "target_audience", "distinguishing_features",
)

# Module-level cache for loaded data
_catalog_index: list[dict[str, Any]] | None = None
_all_embeddings: np.ndarray | None = None
_clip_model: CLIPModel | None = None
_clip_processor: CLIPProcessor | None = None
_industry_profiles: dict | None = None


def load_index() -> tuple[list[dict[str, Any]], np.ndarray]:
    """Load catalog index and embeddings into memory (cached)."""
    global _catalog_index, _all_embeddings

    if _catalog_index is None:
        with open(settings.catalog_index_path) as f:
            _catalog_index = json.load(f)

    if _all_embeddings is None:
        _all_embeddings = np.load(settings.embeddings_path)
        # Normalize
        norms = np.linalg.norm(_all_embeddings, axis=1, keepdims=True)
        _all_embeddings = _all_embeddings / np.maximum(norms, 1e-8)

    return _catalog_index, _all_embeddings


def load_industry_profiles() -> dict:
    """Load industry × style profiles (cached). Returns empty dict if file not found."""
    global _industry_profiles
    if _industry_profiles is None:
        try:
            with open(settings.industry_profiles_path) as f:
                _industry_profiles = json.load(f)
        except FileNotFoundError:
            _industry_profiles = {}
    return _industry_profiles


def _get_clip() -> tuple[CLIPModel, CLIPProcessor]:
    """Lazy-load CLIP text encoder."""
    global _clip_model, _clip_processor
    if _clip_model is None:
        _clip_model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
        _clip_processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
        _clip_model.eval()
    return _clip_model, _clip_processor


# ── Industry group helpers ──────────────────────────────────────────────────

def _get_industry_groups(profiles: dict) -> dict[str, list[str]]:
    """Extract industry_groups mapping from profiles, or return built-in fallback."""
    if profiles and "industry_groups" in profiles:
        return profiles["industry_groups"]
    # Minimal built-in fallback (subset of what the corpus script defines)
    return {
        "finance_group": ["finance", "fintech", "insurance", "banking", "crypto_web3", "defi"],
        "health_group": ["health", "fitness_wellness", "mental_health"],
        "tech_group": ["technology", "saas", "ai_ml", "developer_tools", "devops", "security"],
        "ecommerce_group": ["ecommerce", "fashion", "beauty", "food_beverage", "restaurant"],
        "media_group": ["media", "news", "podcast", "entertainment", "sports"],
        "education_group": ["education", "edtech"],
        "creative_group": ["creative_agency", "design_studio"],
        "real_estate_group": ["real_estate", "proptech"],
        "travel_group": ["travel", "hospitality"],
        "gaming_group": ["gaming", "esports"],
    }


def _same_industry_group(industry_a: str, industry_b: str, groups: dict[str, list[str]]) -> bool:
    """Return True if both industries belong to the same group."""
    for members in groups.values():
        if industry_a in members and industry_b in members:
            return True
    return False


def _match_intent_to_profile(intent: UserIntent, profiles: dict) -> str | None:
    """Find the best industry×style archetype key for the given intent.

    Looks for profiles whose industries include the intent's industry, and whose
    color_modes and visual_styles overlap with the intent's signals.
    """
    profile_defs = profiles.get("profiles", {})
    if not profile_defs or not intent.industry:
        return None

    best_key: str | None = None
    best_score = 0

    for key, profile in profile_defs.items():
        if intent.industry not in profile.get("industries", []):
            continue

        score = 1  # industry match is the baseline

        # Color mode bonus
        if intent.color_preference and intent.color_preference in profile.get("color_modes", []):
            score += 2

        # Style keyword overlap with archetype's visual_styles
        if intent.style_keywords:
            for arch_style in profile.get("visual_styles", []):
                if any(kw in arch_style for kw in intent.style_keywords):
                    score += 1
                    break

        if score > best_score:
            best_score = score
            best_key = key

    return best_key


# ── Composite scoring ───────────────────────────────────────────────────────

def _composite_score(
    candidate: dict[str, Any],
    vector_sim: float,
    intent: UserIntent,
    groups: dict[str, list[str]],
) -> float:
    """Compute a weighted composite retrieval score for a candidate entry.

    Weights:
      0.45 — CLIP vector similarity       (visual style match)
      0.25 — Industry match score         (exact=1.0, same group=0.5, miss=0.0, no intent=0.5)
      0.15 — Industry×style profile match (exact=1.0, miss=0.0, no intent=0.5)
      0.10 — Quality score normalized     (1-5 → 0.0-1.0)
      0.05 — Color mode match             (exact=1.0, miss=0.0, no preference=0.5)
    """
    # 1. Vector similarity (clamped 0-1)
    vsim = max(0.0, min(1.0, vector_sim))

    # 2. Industry match
    c_industry = candidate.get("industry") or ""
    if not intent.industry:
        industry_score = 0.5  # neutral — no preference expressed
    elif c_industry == intent.industry:
        industry_score = 1.0
    elif c_industry and _same_industry_group(c_industry, intent.industry, groups):
        industry_score = 0.5
    else:
        industry_score = 0.0

    # 3. Industry×style profile match
    c_profile = candidate.get("industry_style_profile") or ""
    if not intent.industry_style_profile:
        profile_score = 0.5  # neutral
    elif c_profile == intent.industry_style_profile:
        profile_score = 1.0
    else:
        profile_score = 0.0

    # 4. Quality normalized (1→0.0, 5→1.0)
    raw_quality = candidate.get("quality_score") or 1
    quality_score = (max(1, min(5, int(raw_quality))) - 1) / 4.0

    # 5. Color mode match
    c_color = candidate.get("color_mode") or ""
    if not intent.color_preference:
        color_score = 0.5
    elif c_color == intent.color_preference:
        color_score = 1.0
    else:
        color_score = 0.0

    return (
        0.45 * vsim
        + 0.25 * industry_score
        + 0.15 * profile_score
        + 0.10 * quality_score
        + 0.05 * color_score
    )


# ── Metadata filter ────────────────────────────────────────────────────────

def metadata_filter(catalog: list[dict[str, Any]], intent: UserIntent) -> list[dict[str, Any]]:
    """Filter catalog to a manageable candidate set for scoring.

    Applies only functional/objective filters (page_type, quality floor, color mode).
    Industry matching is intentionally handled by composite scoring, not here, so
    that related-industry results are not hard-excluded.
    """
    candidates = catalog

    # page_type filter (exact functional match)
    if intent.page_type:
        filtered = [c for c in candidates if c.get("page_type") == intent.page_type]
        if len(filtered) >= 10:
            candidates = filtered

    # Quality floor: prefer quality >= 3; fall through to all if not enough
    filtered = [c for c in candidates if c.get("quality_score", 0) >= 3]
    if len(filtered) >= 10:
        candidates = filtered

    # Color mode filter (optional soft pass — only applied if enough results remain)
    if intent.color_preference:
        filtered = [c for c in candidates if c.get("color_mode") == intent.color_preference]
        if len(filtered) >= 5:
            candidates = filtered

    return candidates


# ── Vector similarity ───────────────────────────────────────────────────────

def _compute_all_similarities(
    query_text: str,
    candidates: list[dict[str, Any]],
    embeddings: np.ndarray,
) -> np.ndarray:
    """Compute CLIP cosine similarity between query_text and all candidates."""
    model, processor = _get_clip()

    with torch.no_grad():
        inputs = processor(text=[query_text], return_tensors="pt", padding=True, truncation=True)
        text_out = model.text_model(
            input_ids=inputs["input_ids"],
            attention_mask=inputs["attention_mask"],
        )
        text_features = model.text_projection(text_out.pooler_output)
        text_features = text_features / text_features.norm(dim=-1, keepdim=True)
        query_vec = text_features.cpu().numpy()[0]  # (512,)

    row_indices = [c["row_idx"] for c in candidates]
    candidate_embs = embeddings[row_indices]  # (N, 512)
    return candidate_embs @ query_vec  # (N,) cosine similarities


def vector_search(
    query_text: str,
    candidates: list[dict[str, Any]],
    embeddings: np.ndarray,
    top_k: int = 5,
) -> list[RetrievalResult]:
    """Encode query with CLIP text encoder, rank candidates by cosine similarity.

    Legacy path used by cluster_diverse_retrieve (no composite scoring needed there).
    """
    similarities = _compute_all_similarities(query_text, candidates, embeddings)
    top_indices = np.argsort(similarities)[::-1][:top_k]

    results: list[RetrievalResult] = []
    for idx in top_indices:
        c = candidates[idx]
        descriptor = {k: c[k] for k in DESCRIPTOR_FIELDS if k in c}
        results.append(
            RetrievalResult(
                domain=c["domain"],
                cluster_id=c["cluster_id"],
                row_idx=c["row_idx"],
                similarity=float(similarities[idx]),
                descriptor=descriptor,
                screenshot_path=domain_to_screenshot_path(c["domain"]),
            )
        )
    return results


# ── Query building ─────────────────────────────────────────────────────────

def _build_visual_query(prompt: str, intent: UserIntent) -> str:
    """Build a CLIP-optimized query using visual style terms, not domain nouns.

    CLIP's text encoder has strong visual grounding for style descriptors ("minimal",
    "dark", "editorial") but weak grounding for industry nouns ("aerospace",
    "fintech"). Stripping domain terms and querying on style keywords alone yields
    more visually relevant results.
    """
    parts: list[str] = []
    if intent.style_keywords:
        parts.extend(intent.style_keywords)
    if intent.color_preference:
        parts.append(intent.color_preference)
    if intent.page_type:
        parts.append(intent.page_type.replace("_", " "))
    # brand_tier carries some visual signal (e.g. "startup modern" → bold, gradient)
    if intent.brand_tier and intent.brand_tier != "unknown":
        parts.append(intent.brand_tier.replace("_", " "))
    # Need at least two visual signals to be meaningful; else fall back to full prompt.
    if len(parts) >= 2:
        return " ".join(parts)
    return prompt


# ── Coverage reporting ─────────────────────────────────────────────────────

def get_corpus_coverage(intent: UserIntent) -> dict:
    """Report how well the corpus covers the requested intent."""
    catalog, _ = load_index()
    profiles = load_industry_profiles()
    groups = _get_industry_groups(profiles)
    coverage: dict = {}

    if intent.industry:
        exact_count = sum(1 for c in catalog if c.get("industry") == intent.industry)
        related_industries = [
            ind for grp in groups.values()
            if intent.industry in grp
            for ind in grp
            if ind != intent.industry
        ]
        related_count = sum(
            1 for c in catalog if c.get("industry") in related_industries
        )
        coverage["industry"] = {
            "requested": intent.industry,
            "exact_count": exact_count,
            "related_count": related_count,
            "related_industries": related_industries[:5],
            "covered": exact_count >= 10,
            "note": (
                f"No {intent.industry}-specific sites in corpus — references shown are "
                f"visual style matches only, not industry references. "
                f"Treat them as design inspiration, not domain examples."
            ) if exact_count < 10 else (
                f"{exact_count} {intent.industry} sites available in corpus."
            ),
        }

    if intent.page_type:
        count = sum(1 for c in catalog if c.get("page_type") == intent.page_type)
        coverage["page_type"] = {
            "requested": intent.page_type,
            "count": count,
            "covered": count >= 5,
        }

    if intent.industry_style_profile:
        coverage["style_profile"] = {
            "matched_archetype": intent.industry_style_profile,
            "description": (
                profiles.get("profiles", {})
                .get(intent.industry_style_profile, {})
                .get("description", "")
            ),
        }

    return coverage


# ── Cluster-diverse retrieval ───────────────────────────────────────────────

def cluster_diverse_retrieve(
    intent: UserIntent,
    top_k: int = 5,
) -> list[RetrievalResult]:
    """Retrieve references maximizing cluster diversity rather than similarity score."""
    catalog, _ = load_index()
    candidates = metadata_filter(catalog, intent)

    # De-duplicate by domain
    seen: set[str] = set()
    unique: list[dict] = []
    for c in candidates:
        if c["domain"] not in seen:
            seen.add(c["domain"])
            unique.append(c)

    # Group by cluster, pick best-quality representative from each
    by_cluster: dict[int, list[dict]] = {}
    for c in unique:
        cluster_id = c.get("cluster_id", 0)
        by_cluster.setdefault(cluster_id, []).append(c)

    cluster_reps: list[dict] = []
    for members in by_cluster.values():
        best = max(members, key=lambda c: c.get("quality_score", 0))
        cluster_reps.append(best)

    cluster_reps.sort(key=lambda c: c.get("quality_score", 0), reverse=True)
    final = cluster_reps[:top_k]

    results: list[RetrievalResult] = []
    for c in final:
        descriptor = {k: c[k] for k in DESCRIPTOR_FIELDS if k in c}
        results.append(
            RetrievalResult(
                domain=c["domain"],
                cluster_id=c["cluster_id"],
                row_idx=c["row_idx"],
                similarity=0.0,
                descriptor=descriptor,
                screenshot_path=domain_to_screenshot_path(c["domain"]),
            )
        )
    return results


# ── Main retrieval ─────────────────────────────────────────────────────────

def retrieve(
    prompt: str,
    intent: UserIntent,
    top_k: int = 5,
    no_vector: bool = False,
    verbose: bool = False,
) -> list[RetrievalResult]:
    """Full retrieval pipeline: metadata filter → composite scoring.

    Composite scoring combines CLIP vector similarity (45%), industry match (25%),
    industry×style profile match (15%), quality (10%), and color mode (5%).
    This means industry signal reinforces style signal rather than acting as a
    hard gate, so related industries surface even when exact matches are scarce.
    """
    catalog, embeddings = load_index()
    profiles = load_industry_profiles()
    groups = _get_industry_groups(profiles)

    if verbose:
        print(f"Loaded {len(catalog)} catalog entries", file=sys.stderr)

    # Resolve industry_style_profile from intent signals if not already set
    if intent.industry_style_profile is None:
        intent.industry_style_profile = _match_intent_to_profile(intent, profiles)
        if verbose and intent.industry_style_profile:
            print(f"Matched intent to profile: {intent.industry_style_profile}", file=sys.stderr)

    candidates = metadata_filter(catalog, intent)
    if verbose:
        print(f"After metadata filter: {len(candidates)} candidates", file=sys.stderr)

    # De-duplicate candidates by domain (keep first occurrence)
    seen: set[str] = set()
    unique_candidates: list[dict] = []
    for c in candidates:
        if c["domain"] not in seen:
            seen.add(c["domain"])
            unique_candidates.append(c)

    if no_vector:
        # Sort by composite score using only metadata signals (no vector similarity)
        scored = [
            (_composite_score(c, 0.5, intent, groups), c)
            for c in unique_candidates
        ]
        scored.sort(key=lambda x: x[0], reverse=True)

        results: list[RetrievalResult] = []
        for score, c in scored[:top_k]:
            descriptor = {k: c[k] for k in DESCRIPTOR_FIELDS if k in c}
            results.append(
                RetrievalResult(
                    domain=c["domain"],
                    cluster_id=c["cluster_id"],
                    row_idx=c["row_idx"],
                    similarity=0.0,
                    descriptor=descriptor,
                    screenshot_path=domain_to_screenshot_path(c["domain"]),
                )
            )
        return results

    # Compute CLIP similarities for all unique candidates
    visual_query = _build_visual_query(prompt, intent)
    similarities = _compute_all_similarities(visual_query, unique_candidates, embeddings)

    # Rank by composite score
    scored = [
        (_composite_score(c, float(similarities[i]), intent, groups), i)
        for i, c in enumerate(unique_candidates)
    ]
    scored.sort(key=lambda x: x[0], reverse=True)

    if verbose:
        print(f"Top {min(top_k, len(scored))} composite scores:", file=sys.stderr)
        for score, idx in scored[:top_k]:
            c = unique_candidates[idx]
            print(
                f"  {c['domain']} (composite={score:.3f}, "
                f"vsim={similarities[idx]:.3f}, "
                f"industry={c.get('industry')}, "
                f"profile={c.get('industry_style_profile')})",
                file=sys.stderr,
            )

    results = []
    for score, idx in scored[:top_k]:
        c = unique_candidates[idx]
        descriptor = {k: c[k] for k in DESCRIPTOR_FIELDS if k in c}
        results.append(
            RetrievalResult(
                domain=c["domain"],
                cluster_id=c["cluster_id"],
                row_idx=c["row_idx"],
                similarity=float(similarities[idx]),
                descriptor=descriptor,
                screenshot_path=domain_to_screenshot_path(c["domain"]),
            )
        )

    return results
