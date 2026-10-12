"""Filtered views over posts and ad rows, plus dataset metadata.

This is the single place where platform / campaign / date filters are applied,
so every page slices the same dataset in the same way. A real platform API
integration would replace the functions in this module.
"""
from __future__ import annotations

from datetime import date, timedelta

from app.data.storage import get_store
from app.repositories import campaign_repository, content_repository
from app.schemas.analytics import Post
from app.schemas.campaigns import Campaign, CampaignDaily


def get_meta() -> dict:
    return get_store().read()["meta"]


def as_of() -> date:
    return date.fromisoformat(get_meta()["anchor_date"])


def first_date() -> date:
    return as_of() - timedelta(days=int(get_meta()["history_days"]) - 1)


def select_posts(platform: str = "all", campaign: str = "all",
                 start: date | None = None, end: date | None = None) -> list[Post]:
    """Published posts matching the filters (date applies to publication date)."""
    out = []
    for p in content_repository.list_posts():
        if p.status != "published" or p.published_at is None:
            continue
        d = p.published_at.date()
        if platform != "all" and p.platform != platform:
            continue
        if campaign != "all" and p.campaign_id != campaign:
            continue
        if start and d < start:
            continue
        if end and d > end:
            continue
        out.append(p)
    return out


def select_campaigns(platform: str = "all", campaign: str = "all") -> list[Campaign]:
    return [c for c in campaign_repository.list_campaigns()
            if (platform == "all" or c.platform == platform)
            and (campaign == "all" or c.id == campaign)]


def select_ad_rows(platform: str = "all", campaign: str = "all",
                   start: date | None = None, end: date | None = None) -> list[CampaignDaily]:
    ids = {c.id for c in select_campaigns(platform, campaign)}
    return [r for r in campaign_repository.list_daily()
            if r.campaign_id in ids
            and (start is None or r.date >= start)
            and (end is None or r.date <= end)]
