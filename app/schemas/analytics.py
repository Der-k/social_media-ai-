"""Pydantic models for posts and dashboard filters."""
from __future__ import annotations

from datetime import datetime
from typing import Literal, get_args

from pydantic import BaseModel, Field, computed_field, field_validator

Platform = Literal["Facebook", "Instagram", "LinkedIn", "TikTok"]
ContentType = Literal[
    "educational", "promotional", "industry_news", "short_video",
    "carousel", "testimonial", "poll",
]
PostStatus = Literal["published", "proposed", "draft"]

PLATFORMS: list[str] = ["Facebook", "Instagram", "LinkedIn", "TikTok"]
CONTENT_TYPES: list[str] = list(get_args(ContentType))
ALLOWED_DAYS = {7, 14, 30, 90}


class Post(BaseModel):
    id: str
    caption: str
    platform: Platform
    content_type: ContentType
    topic: str
    status: PostStatus
    created_at: datetime
    published_at: datetime | None = None      # published posts
    scheduled_for: datetime | None = None     # drafts / proposed posts
    reach: int | None = None
    impressions: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    link_clicks: int | None = None
    campaign_id: str | None = None
    source: Literal["sample", "manual", "ai", "rules"] = "sample"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def engagements(self) -> int | None:
        parts = [self.likes, self.comments, self.shares, self.saves]
        if all(p is None for p in parts):
            return None
        return sum(p or 0 for p in parts)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def engagement_rate(self) -> float | None:
        """Engagements divided by reach. None when reach is missing or zero."""
        if not self.reach or self.engagements is None:
            return None
        return self.engagements / self.reach


class DashboardFilters(BaseModel):
    """Shared filter state, carried in the query string on every page."""
    days: int = 30
    platform: str = "all"
    campaign: str = "all"

    @field_validator("days")
    @classmethod
    def _days(cls, v: int) -> int:
        return v if v in ALLOWED_DAYS else 30

    @field_validator("platform")
    @classmethod
    def _platform(cls, v: str) -> str:
        return v if v in PLATFORMS else "all"

    @property
    def query_string(self) -> str:
        return f"days={self.days}&platform={self.platform}&campaign={self.campaign}"
