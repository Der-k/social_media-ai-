"""Pydantic models for the content library: query filters and draft input."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.schemas.analytics import CONTENT_TYPES, ContentType, DashboardFilters, Platform

SORTS = {"newest", "oldest", "er_desc", "er_asc", "reach_desc", "clicks_desc"}
STATUSES = {"all", "published", "draft", "proposed"}


class ContentFilters(DashboardFilters):
    """Global filters (days/platform/campaign) plus the library's own controls."""
    q: str = ""
    format: str = "all"
    topic: str = "all"
    status: str = "all"
    sort: str = "newest"
    page: int = 1

    @field_validator("q")
    @classmethod
    def _q(cls, v: str) -> str:
        return v.strip()[:80]

    @field_validator("format")
    @classmethod
    def _format(cls, v: str) -> str:
        return v if v in CONTENT_TYPES else "all"

    @field_validator("status")
    @classmethod
    def _status(cls, v: str) -> str:
        return v if v in STATUSES else "all"

    @field_validator("sort")
    @classmethod
    def _sort(cls, v: str) -> str:
        return v if v in SORTS else "newest"

    @field_validator("page")
    @classmethod
    def _page(cls, v: int) -> int:
        return max(1, v)


class DraftInput(BaseModel):
    """A draft or proposed post entered by hand. Nothing here is ever published."""
    model_config = ConfigDict(str_strip_whitespace=True)

    platform: Platform
    content_type: ContentType
    topic: str = Field(min_length=2, max_length=60)
    caption: str = Field(min_length=10, max_length=3000)
    status: Literal["draft", "proposed"] = "draft"
    scheduled_for: datetime | None = None
    campaign_id: str | None = None

    @field_validator("campaign_id", mode="before")
    @classmethod
    def _blank_campaign(cls, v):
        return v or None
