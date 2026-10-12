"""Data access for recommendations and the batches they were generated in."""
from __future__ import annotations

from app.data.storage import get_store
from app.schemas.recommendations import Recommendation, RecommendationBatch


def list_recommendations() -> list[Recommendation]:
    return [Recommendation.model_validate(r) for r in get_store().read()["recommendations"]]


def get_recommendation(rec_id: str) -> Recommendation | None:
    for r in get_store().read()["recommendations"]:
        if r["id"] == rec_id:
            return Recommendation.model_validate(r)
    return None


def list_batches() -> list[RecommendationBatch]:
    """Generated batches only (the seeded sample history has no batch record)."""
    rows = get_store().read().get("recommendation_batches", [])
    return sorted((RecommendationBatch.model_validate(b) for b in rows), key=lambda b: b.created_at)


def next_batch_number() -> int:
    return len(get_store().read().get("recommendation_batches", [])) + 1


def add_batch(batch: RecommendationBatch, recs: list[Recommendation]) -> None:
    def _apply(state: dict) -> None:
        state.setdefault("recommendation_batches", []).append(batch.model_dump(mode="json"))
        state["recommendations"].extend(r.model_dump(mode="json") for r in recs)
    get_store().update(_apply)


def update_recommendation(rec_id: str, **changes) -> Recommendation | None:
    def _apply(state: dict):
        for r in state["recommendations"]:
            if r["id"] == rec_id:
                r.update(changes)
                return r
        return None
    row = get_store().update(_apply)
    return Recommendation.model_validate(row) if row else None
