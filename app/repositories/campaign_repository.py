"""Data access for advertising campaigns and their daily metric rows."""
from __future__ import annotations

from app.data.storage import get_store
from app.schemas.campaigns import Campaign, CampaignDaily


def list_campaigns() -> list[Campaign]:
    return [Campaign.model_validate(c) for c in get_store().read()["campaigns"]]


def get_campaign(campaign_id: str) -> Campaign | None:
    for c in get_store().read()["campaigns"]:
        if c["id"] == campaign_id:
            return Campaign.model_validate(c)
    return None


def list_daily(campaign_id: str | None = None) -> list[CampaignDaily]:
    rows = get_store().read()["campaign_daily"]
    return [CampaignDaily.model_validate(r) for r in rows
            if campaign_id is None or r["campaign_id"] == campaign_id]
