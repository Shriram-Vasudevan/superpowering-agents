from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.config import settings


def domain_to_screenshot_filename(domain: str) -> str:
    """Convert a domain like '1999.agency' to '1999_agency.png'."""
    return domain.replace(".", "_") + ".png"


def domain_to_screenshot_path(domain: str) -> Path:
    return settings.screenshots_dir / domain_to_screenshot_filename(domain)


def load_catalog() -> dict[str, Any]:
    """Load and return the raw style_catalog.json."""
    with open(settings.catalog_path) as f:
        return json.load(f)


def extract_catalog_domains(catalog: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract flat list of (domain, cluster_id, descriptor) from catalog."""
    records: list[dict[str, Any]] = []
    for style in catalog["styles"]:
        cluster_id = style["cluster_id"]
        descriptor = style["descriptor"]
        for member in style["members"]:
            records.append(
                {
                    "domain": member["domain"],
                    "cluster_id": cluster_id,
                    "category_hint": member.get("category_hint", ""),
                    **descriptor,
                }
            )
    return records
