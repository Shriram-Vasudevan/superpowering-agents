"""Data-driven intent extraction from user prompts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from functools import lru_cache

from src.config import settings


@dataclass
class UserIntent:
    page_type: str | None = None
    industry: str | None = None
    business_model: str | None = None        # b2b_saas | b2c_consumer | marketplace | ...
    brand_tier: str | None = None            # startup_modern | enterprise_trusted | ...
    industry_style_profile: str | None = None  # archetype key e.g. "fintech_dark_minimal"
    color_preference: str | None = None
    style_keywords: list[str] = field(default_factory=list)
    raw_description: str = ""


# Color preference keywords remain lightweight and generic.
COLOR_KEYWORDS: dict[str, list[str]] = {
    "dark": ["dark", "dark mode", "dark theme", "black", "moody"],
    "light": ["light", "light mode", "white", "bright", "clean"],
    "colorful": ["colorful", "vibrant", "rainbow", "multicolor", "gradient"],
}

# Style terms used for retrieval context expansion.
STYLE_TERMS: list[str] = [
    "minimal", "minimalist", "bold", "gradient", "glassmorphism", "brutalist",
    "retro", "vintage", "modern", "futuristic", "elegant", "playful",
    "professional", "sleek", "animated", "3d", "illustration", "typography",
    "geometric", "organic", "flat", "skeuomorphic", "neumorphism", "monochrome",
    "serif", "sans-serif", "rounded", "sharp", "editorial", "magazine",
]

# Semantic aliases: common words/phrases in user prompts → industry taxonomy value.
# Used as a fallback when the keyword overlap scorer returns no confident match.
INDUSTRY_ALIASES: dict[str, str] = {
    # health & wellness
    "hospital": "health",
    "clinic": "health",
    "doctor": "health",
    "medical": "health",
    "healthcare": "health",
    "dental": "health",
    "dentist": "health",
    "pharmacy": "health",
    "therapy": "mental_health",
    "therapist": "mental_health",
    "counseling": "mental_health",
    "mental health": "mental_health",
    "gym": "fitness_wellness",
    "workout": "fitness_wellness",
    "wellness": "fitness_wellness",
    "yoga": "fitness_wellness",
    "nutrition": "fitness_wellness",
    # finance
    "bank": "banking",
    "banking": "banking",
    "mortgage": "banking",
    "loan": "finance",
    "invest": "finance",
    "investment": "finance",
    "wealth": "finance",
    "insurance": "insurance",
    "insure": "insurance",
    "payments": "fintech",
    "payment": "fintech",
    "stripe": "fintech",
    "neobank": "fintech",
    "crypto": "crypto_web3",
    "blockchain": "crypto_web3",
    "nft": "defi",
    "defi": "defi",
    "web3": "crypto_web3",
    # ecommerce & consumer
    "shop": "ecommerce",
    "store": "ecommerce",
    "marketplace": "ecommerce",
    "fashion": "fashion",
    "clothing": "fashion",
    "apparel": "fashion",
    "shoes": "fashion",
    "luxury": "fashion",
    "beauty": "beauty",
    "cosmetics": "beauty",
    "skincare": "beauty",
    "makeup": "beauty",
    # food & beverage
    "restaurant": "restaurant",
    "food": "food_beverage",
    "cafe": "food_beverage",
    "coffee": "food_beverage",
    "beverage": "food_beverage",
    "brewery": "food_beverage",
    "catering": "food_beverage",
    # real estate
    "real estate": "real_estate",
    "realty": "real_estate",
    "property": "real_estate",
    "apartment": "real_estate",
    "housing": "real_estate",
    "proptech": "proptech",
    # travel & hospitality
    "travel": "travel",
    "airline": "travel",
    "flight": "travel",
    "tourism": "travel",
    "hotel": "hospitality",
    "airbnb": "hospitality",
    "resort": "hospitality",
    "vacation": "hospitality",
    # gaming
    "game": "gaming",
    "gaming": "gaming",
    "esports": "esports",
    "tournament": "esports",
    # media & content
    "news": "news",
    "newspaper": "news",
    "journalism": "news",
    "blog": "media",
    "podcast": "podcast",
    "newsletter": "media",
    "magazine": "media",
    "streaming": "media",
    "sports": "sports",
    "entertainment": "entertainment",
    # education
    "school": "education",
    "university": "education",
    "college": "education",
    "education": "education",
    "learning": "edtech",
    "course": "edtech",
    "bootcamp": "edtech",
    "edtech": "edtech",
    "tutoring": "edtech",
    "lms": "edtech",
    # developer / tech tools
    "developer": "developer_tools",
    "cli": "developer_tools",
    "sdk": "developer_tools",
    "open source": "developer_tools",
    "library": "developer_tools",
    "npm": "developer_tools",
    "devops": "devops",
    "ci/cd": "devops",
    "kubernetes": "devops",
    "docker": "devops",
    "monitoring": "devops",
    "observability": "devops",
    "cloud": "devops",
    "security": "security",
    "cybersecurity": "security",
    "pentest": "security",
    "vulnerability": "security",
    # business services
    "legal": "legal",
    "lawyer": "legal",
    "law firm": "legal",
    "attorney": "legal",
    "nonprofit": "nonprofit",
    "charity": "nonprofit",
    "ngo": "nonprofit",
    "hr": "hr_recruiting",
    "recruiting": "hr_recruiting",
    "hiring": "hr_recruiting",
    "staffing": "hr_recruiting",
    "logistics": "logistics",
    "shipping": "logistics",
    "supply chain": "logistics",
    "delivery": "logistics",
    "freight": "logistics",
    "automotive": "automotive",
    "car": "automotive",
    "vehicle": "automotive",
    "ev": "automotive",
    # creative
    "agency": "creative_agency",
    "design agency": "creative_agency",
    "design studio": "design_studio",
    "branding": "creative_agency",
    "advertising": "creative_agency",
    # ai & ml
    "ai": "ai_ml",
    "machine learning": "ai_ml",
    "llm": "ai_ml",
    "chatbot": "ai_ml",
}

# Business model keywords for basic extraction from user prompts.
BUSINESS_MODEL_KEYWORDS: list[tuple[str, str]] = [
    ("b2b", "b2b_saas"),
    ("enterprise", "enterprise_software"),
    ("b2c", "b2c_consumer"),
    ("consumer app", "b2c_consumer"),
    ("marketplace", "marketplace"),
    ("open source", "open_source"),
    ("for developers", "developer_tool"),
    ("api", "api_service"),
    ("agency", "agency_studio"),
    ("nonprofit", "nonprofit"),
]

# Brand tier keywords.
BRAND_TIER_KEYWORDS: list[tuple[str, str]] = [
    ("enterprise", "enterprise_trusted"),
    ("startup", "startup_modern"),
    ("luxury", "luxury_premium"),
    ("premium", "minimal_premium"),
    ("playful", "consumer_playful"),
    ("creative", "creative_bold"),
    ("corporate", "corporate_formal"),
    ("community", "community_driven"),
    ("developer", "developer_focused"),
    ("for developers", "developer_focused"),
]


def _normalize(text: str) -> str:
    return " ".join(text.strip().lower().split())


def _tokenize(text: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", text.lower()))


@lru_cache(maxsize=1)
def _load_taxonomy() -> dict[str, list[str]]:
    """Load page_type and industry taxonomy directly from indexed catalog."""
    with open(settings.catalog_index_path) as f:
        catalog = json.load(f)

    page_types = sorted({c.get("page_type") for c in catalog if c.get("page_type")})
    industries = sorted({c.get("industry") for c in catalog if c.get("industry")})

    return {
        "page_types": page_types,
        "industries": industries,
    }


def _label_to_phrase(label: str) -> str:
    return label.replace("_", " ").strip().lower()


def _score_label(prompt: str, prompt_tokens: set[str], label: str) -> float:
    """Compute soft confidence that a taxonomy label matches the prompt."""
    label_phrase = _label_to_phrase(label)
    label_tokens = _tokenize(label_phrase)
    if not label_tokens:
        return 0.0

    overlap = len(prompt_tokens & label_tokens) / len(label_tokens)

    phrase_boost = 0.0
    if label_phrase in prompt:
        phrase_boost += 0.8

    # Token-order hint for labels like "landing page" or "real estate".
    if len(label_tokens) >= 2:
        ordered = " ".join(label_phrase.split())
        if ordered in prompt:
            phrase_boost += 0.3

    generic_penalty = 0.0
    if label in {"general", "non_applicable"}:
        generic_penalty = 0.2

    return overlap + phrase_boost - generic_penalty


def _pick_best_label(prompt: str, labels: list[str], threshold: float = 0.75) -> str | None:
    """Choose a taxonomy label only when confidence is high enough."""
    prompt_norm = _normalize(prompt)
    prompt_tokens = _tokenize(prompt_norm)

    if not prompt_tokens:
        return None

    scored = [(_score_label(prompt_norm, prompt_tokens, label), label) for label in labels]
    scored.sort(reverse=True)

    if not scored:
        return None

    best_score, best_label = scored[0]
    runner_up = scored[1][0] if len(scored) > 1 else 0.0

    # Require both absolute confidence and a margin over the next candidate.
    if best_score >= threshold and (best_score - runner_up) >= 0.1:
        return best_label

    return None


def _try_alias_match(prompt: str) -> str | None:
    """Fallback industry detection via semantic alias table.

    Scans for multi-word aliases first (longer matches take priority), then
    single-word aliases. Returns the first confident match or None.
    """
    prompt_lower = _normalize(prompt)
    # Sort by length descending so multi-word aliases take priority
    sorted_aliases = sorted(INDUSTRY_ALIASES.items(), key=lambda x: -len(x[0]))
    for phrase, industry in sorted_aliases:
        if phrase in prompt_lower:
            return industry
    return None


def _extract_business_model(prompt: str) -> str | None:
    """Extract a business_model hint from the prompt."""
    lower = _normalize(prompt)
    for phrase, model in BUSINESS_MODEL_KEYWORDS:
        if phrase in lower:
            return model
    return None


def _extract_brand_tier(prompt: str) -> str | None:
    """Extract a brand_tier hint from the prompt."""
    lower = _normalize(prompt)
    for phrase, tier in BRAND_TIER_KEYWORDS:
        if phrase in lower:
            return tier
    return None


def extract_intent(
    prompt: str,
    page_type_override: str | None = None,
    industry_override: str | None = None,
    business_model_override: str | None = None,
    brand_tier_override: str | None = None,
) -> UserIntent:
    """Extract structured intent from a free-text prompt using catalog-driven taxonomy."""
    lower = prompt.lower()
    taxonomy = _load_taxonomy()

    intent = UserIntent(raw_description=prompt)

    # Page type: override first, else taxonomy match.
    if page_type_override:
        intent.page_type = page_type_override
    else:
        intent.page_type = _pick_best_label(lower, taxonomy["page_types"])

    # Industry: override → taxonomy match → alias fallback.
    if industry_override:
        intent.industry = industry_override
    else:
        intent.industry = _pick_best_label(lower, taxonomy["industries"])
        if intent.industry is None:
            intent.industry = _try_alias_match(prompt)

    # Business model: override → keyword extraction.
    intent.business_model = business_model_override or _extract_business_model(prompt)

    # Brand tier: override → keyword extraction.
    intent.brand_tier = brand_tier_override or _extract_brand_tier(prompt)

    # Color preference.
    for color, keywords in COLOR_KEYWORDS.items():
        for kw in sorted(keywords, key=len, reverse=True):
            if kw in lower:
                intent.color_preference = color
                break
        if intent.color_preference:
            break

    # Style keywords for retrieval expansion.
    intent.style_keywords = [term for term in STYLE_TERMS if term in lower]

    # industry_style_profile is resolved in the retrieval layer (needs profile catalog).
    # Left as None here; retrieval.py sets it on the returned intent when a match is found.

    return intent
