"""Shared Pydantic request/response models for the superpower service layer."""

from __future__ import annotations

from pydantic import BaseModel, Field


# ── Request models ──────────────────────────────────────────────────────────

class RetrieveRequest(BaseModel):
    prompt: str
    page_type: str | None = None
    industry: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    no_vector: bool = False


class GenerateRequest(BaseModel):
    prompt: str
    page_type: str | None = None
    industry: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    no_vector: bool = False


class ContextRequest(BaseModel):
    prompt: str
    page_type: str | None = None
    industry: str | None = None
    top_k: int = Field(default=5, ge=1, le=20)
    no_vector: bool = False


# ── Response models ─────────────────────────────────────────────────────────

class IntentInfo(BaseModel):
    page_type: str | None = None
    industry: str | None = None
    business_model: str | None = None
    brand_tier: str | None = None
    industry_style_profile: str | None = None
    color_preference: str | None = None
    style_keywords: list[str] = Field(default_factory=list)


class ReferenceItem(BaseModel):
    domain: str
    cluster_id: int
    similarity: float
    descriptor: dict
    screenshot_base64: str


class RetrieveResponse(BaseModel):
    intent: IntentInfo
    references: list[ReferenceItem]


class GenerateResponse(BaseModel):
    intent: IntentInfo
    code: str
    references: list[ReferenceItem]


class ContentBlock(BaseModel):
    type: str  # "text" or "image"
    text: str | None = None
    media_type: str | None = None  # e.g. "image/jpeg"
    data: str | None = None  # base64-encoded image data


class ContextResponse(BaseModel):
    system_prompt: str
    messages: list[dict]  # [{"role": "user", "content": [ContentBlock, ...]}]
    metadata: dict = Field(default_factory=dict)
