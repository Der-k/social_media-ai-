"""Pydantic models for content recommendations.

Two groups:
  * Stored objects (Recommendation, RecommendationBatch): what the page shows and what is saved.
  * LLM output (LLMRecommendation, LLMRecommendationSet): only the *wording* the model may supply.
    Platform, format, confidence and supporting data are always set by Python, never by the model.
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.analytics import ContentType, Platform

RecKind = Literal["publish_more", "test", "reduce", "repurpose", "support_campaign"]
SUCCESS_METRICS = ["Engagement rate", "Reach", "Saves per post", "Shares per post", "Comments", "Link clicks"]


class SupportingStat(BaseModel):
    label: str
    value: str


class Recommendation(BaseModel):
    id: str
    batch_id: str
    priority: int = Field(ge=1)
    kind: RecKind = "publish_more"
    topic: str
    format: ContentType
    platform: Platform
    caption_brief: str
    reason: str
    reason_source: Literal["ai", "template", "sample"] = "sample"
    supporting_data: list[SupportingStat] = []
    posting_window: str | None = None
    confidence: Literal["high", "medium", "low"]
    confidence_note: str = ""
    evidence_n: int = 0
    call_to_action: str
    success_metric: str
    focus: Literal["engagement", "reach"] = "engagement"
    is_test: bool = False            # True when data is too thin to claim a trend
    campaign_id: str | None = None
    in_pipeline: str | None = None   # note when a similar draft or planned post already exists
    status: Literal["new", "saved", "dismissed"] = "new"
    source: Literal["sample", "ai", "rules"] = "sample"
    created_at: datetime
    saved_post_id: str | None = None


class RecommendationBatch(BaseModel):
    id: str
    created_at: datetime
    source: Literal["ai", "rules"]
    model: str | None = None
    fingerprint: str
    posts_analysed: int
    candidate_count: int
    summary: str
    summary_source: Literal["ai", "template"] = "template"


class GenerateRecommendationsRequest(BaseModel):
    mode: Literal["ai", "rules"] = "ai"
    fresh: bool = False          # True = analyse again even if the data has not changed


class LLMRecommendation(BaseModel):
    """One recommendation as worded by the model. Extra keys (e.g. a self-reported
    confidence or a changed platform) are ignored on purpose."""
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")
    candidate_id: str
    topic: str | None = None
    caption_brief: str = Field(min_length=10, max_length=600)
    reason: str = Field(min_length=20, max_length=800)
    call_to_action: str = Field(min_length=3, max_length=200)
    success_metric: str = Field(min_length=3, max_length=40)


class LLMRecommendationSet(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")
    overall_summary: str = Field(min_length=20, max_length=700)
    recommendations: list[LLMRecommendation] = Field(min_length=1, max_length=8)
