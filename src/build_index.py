"""One-time index build: resolve domain → embedding row mapping via CLIP re-embedding.

Usage:
    python -m src.build_index
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from transformers import CLIPModel, CLIPProcessor

from src.config import settings
from src.utils import domain_to_screenshot_path, extract_catalog_domains, load_catalog


def build_index() -> None:
    print("Loading catalog...", file=sys.stderr)
    catalog = load_catalog()
    records = extract_catalog_domains(catalog)
    domains = [r["domain"] for r in records]
    print(f"  {len(records)} catalog entries across {len(set(domains))} unique domains", file=sys.stderr)

    # De-duplicate domains (keep first record per domain for mapping)
    seen: set[str] = set()
    unique_domains: list[str] = []
    for d in domains:
        if d not in seen:
            seen.add(d)
            unique_domains.append(d)

    print("Loading embeddings...", file=sys.stderr)
    all_embeddings = np.load(settings.embeddings_path)  # (3660, 512)
    print(f"  Embedding matrix shape: {all_embeddings.shape}", file=sys.stderr)

    # Normalize the stored embeddings
    norms = np.linalg.norm(all_embeddings, axis=1, keepdims=True)
    all_embeddings_norm = all_embeddings / np.maximum(norms, 1e-8)

    print("Loading CLIP model (ViT-B/32)...", file=sys.stderr)
    model = CLIPModel.from_pretrained("openai/clip-vit-base-patch32")
    processor = CLIPProcessor.from_pretrained("openai/clip-vit-base-patch32")
    model.eval()

    # Batch-embed catalog screenshots
    print(f"Embedding {len(unique_domains)} catalog screenshots...", file=sys.stderr)
    batch_size = 32
    catalog_embeddings: list[np.ndarray] = []
    missing_domains: list[str] = []

    for i in range(0, len(unique_domains), batch_size):
        batch_domains = unique_domains[i : i + batch_size]
        images = []
        valid_indices = []

        for j, domain in enumerate(batch_domains):
            img_path = domain_to_screenshot_path(domain)
            if not img_path.exists():
                missing_domains.append(domain)
                continue
            try:
                img = Image.open(img_path).convert("RGB")
                images.append(img)
                valid_indices.append(i + j)
            except Exception as e:
                print(f"  Warning: failed to load {img_path}: {e}", file=sys.stderr)
                missing_domains.append(domain)

        if not images:
            continue

        with torch.no_grad():
            inputs = processor(images=images, return_tensors="pt", padding=True)
            vision_out = model.vision_model(pixel_values=inputs["pixel_values"])
            feats = model.visual_projection(vision_out.pooler_output)
            feats = feats / feats.norm(dim=-1, keepdim=True)
            catalog_embeddings.append(feats.cpu().numpy())

        progress = min(i + batch_size, len(unique_domains))
        print(f"  {progress}/{len(unique_domains)} done", file=sys.stderr)

    if missing_domains:
        print(f"  Warning: {len(missing_domains)} domains had missing screenshots", file=sys.stderr)

    catalog_emb = np.concatenate(catalog_embeddings, axis=0)  # (N, 512)
    print(f"  Catalog embedding matrix: {catalog_emb.shape}", file=sys.stderr)

    # Match each catalog domain to its row in all_embeddings
    print("Computing similarity matrix...", file=sys.stderr)
    sim_matrix = catalog_emb @ all_embeddings_norm.T  # (N, 3660)
    best_rows = np.argmax(sim_matrix, axis=1)
    best_sims = sim_matrix[np.arange(len(best_rows)), best_rows]

    # Validation
    low_sim = best_sims < 0.95
    if low_sim.any():
        low_count = int(low_sim.sum())
        min_sim = float(best_sims[low_sim].min())
        print(
            f"  Warning: {low_count} domains have similarity < 0.95 (min: {min_sim:.4f})",
            file=sys.stderr,
        )

    unique_rows = set(int(r) for r in best_rows)
    if len(unique_rows) < len(best_rows):
        dup_count = len(best_rows) - len(unique_rows)
        print(f"  Warning: {dup_count} duplicate row assignments", file=sys.stderr)

    # Build the mappings (only for domains that had valid screenshots)
    valid_domains = [d for d in unique_domains if d not in set(missing_domains)]
    domain_to_row: dict[str, int] = {}
    for idx, domain in enumerate(valid_domains):
        domain_to_row[domain] = int(best_rows[idx])

    # Build enriched catalog index: each record gets its row_idx
    catalog_index: list[dict] = []
    for record in records:
        domain = record["domain"]
        if domain in domain_to_row:
            entry = {**record, "row_idx": domain_to_row[domain]}
            catalog_index.append(entry)

    # Save outputs
    settings.index_data_dir.mkdir(parents=True, exist_ok=True)

    with open(settings.domain_to_row_path, "w") as f:
        json.dump(domain_to_row, f, indent=2)
    print(f"Saved {len(domain_to_row)} entries to {settings.domain_to_row_path}", file=sys.stderr)

    with open(settings.catalog_index_path, "w") as f:
        json.dump(catalog_index, f, indent=2)
    print(f"Saved {len(catalog_index)} entries to {settings.catalog_index_path}", file=sys.stderr)

    print("Done!", file=sys.stderr)


if __name__ == "__main__":
    build_index()
