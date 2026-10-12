"""Pydantic models for advertising campaigns and their daily metrics."""
from __future__ import annotations

from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.schemas.analytics import Platform

CampaignStatus = Literal["active", "paused", "completed"]


class Campaign(BaseModel):
    id: str
    name: str
    platform: Platform
    objective: str
    status: CampaignStatus
    budget: float
    start_date: date
    planned_end_date: date
    audience: str = ""
    # False when the objective does not track conversions/revenue (e.g. awareness).
    tracks_conversions: bool = True


class CampaignDaily(BaseModel):
    """One row of ad metrics. conversions/revenue are None when NOT TRACKED,
    which is different from 0 (tracked, but none occurred)."""
    campaign_id: str
    date: date
    spend: float
    impressions: int
    reach: int
    clicks: int
    conversions: int | None = None
    revenue: float | None = None
