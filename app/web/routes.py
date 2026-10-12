"""HTTP routes. Thin: parse input, call a service, render a template or return JSON."""
from __future__ import annotations

import random
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.data.storage import get_store
from app.repositories import analytics_repository as repo
from app.schemas.analytics import PLATFORMS, DashboardFilters
from app.schemas.content import ContentFilters, DraftInput
from app.schemas.assistant import OBJECTIVES, TONES, AskRequest, GenerateRequest
from app.schemas.recommendations import GenerateRecommendationsRequest
from app.services import ai_service, analytics_service, social_analytics_service, assistant_service, content_service, recommendation_service
from app.services.recommendation_service import RecommendationConflict, RecommendationNotFound
from app.services.ai_service import AIUnavailable
from app.services.metrics import TYPE_LABELS
from app.services.content_service import ContentLocked, ContentNotFound, ContentValidationError

router = APIRouter()
templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / "templates"))

Filters = Annotated[DashboardFilters, Query()]
LibraryFilters = Annotated[ContentFilters, Query()]

templates.env.filters["num"] = lambda v: "\u2014" if v is None else f"{v:,.0f}"
templates.env.filters["pct"] = lambda v, d=1: "\u2014" if v is None else f"{v * 100:.{d}f}%"

NAV = [
    ("overview", "Overview", "/", "grid"),
    ("analytics", "Social Analytics", "/analytics", "bars"),
    ("ads", "Advertising Performance", "/ads", "target"),
    ("content", "Content Library", "/content", "library"),
    ("recommendations", "AI Recommendations", "/recommendations", "spark"),
    ("calendar", "Content Calendar", "/calendar", "calendar"),
    ("assistant", "AI Assistant", "/assistant", "chat"),
    ("settings", "Settings", "/settings", "sliders"),
]

# Pages that arrive in later build stages. Each stage replaces its entry with a real template.
PENDING = {
    "ads": dict(title="Advertising Performance", stage=3,
                blurb="Campaign table, detail pages, comparisons, and the Analyze Campaign with AI action."),
    "calendar": dict(title="Content Calendar", stage=7,
                     blurb="Weekly and monthly view of published, proposed and draft posts."),
}


def _ctx(request: Request, f: DashboardFilters, active: str, title: str, **extra) -> dict:
    return dict(nav=NAV, active=active, title=title, filters=f, platforms=PLATFORMS,
                settings=get_settings(), as_of=repo.as_of(), data_seed=repo.get_meta().get("seed"), **extra)


@router.get("/")
async def overview(request: Request, filters: Filters):
    payload = analytics_service.build_dashboard(filters)
    return templates.TemplateResponse(
        request, "dashboard.html", _ctx(request, filters, "overview", "Overview", payload=payload))


@router.get("/analytics")
async def social_analytics(request: Request, filters: Filters):
    payload = social_analytics_service.build_social(filters)
    campaigns = [dict(id=c.id, name=c.name, platform=c.platform) for c in analytics_service.repo.select_campaigns()]
    return templates.TemplateResponse(
        request, "analytics.html",
        _ctx(request, filters, "analytics", "Social Analytics", payload=payload, campaigns=campaigns))


@router.get("/api/analytics")
async def api_social_analytics(filters: Filters):
    return JSONResponse(social_analytics_service.build_social(filters))


@router.get("/settings")
async def settings_page(request: Request, filters: Filters):
    state = get_store().read()
    counts = {k: len(state[k]) for k in ("posts", "campaigns", "campaign_daily", "recommendations")}
    counts["drafts"] = sum(1 for p in state["posts"] if p["status"] == "draft")
    return templates.TemplateResponse(
        request, "settings.html",
        _ctx(request, filters, "settings", "Settings", meta=state["meta"], counts=counts))


def _pending_route(key: str):
    async def view(request: Request, filters: Filters):
        page = PENDING[key]
        return templates.TemplateResponse(
            request, "coming_soon.html", _ctx(request, filters, key, page["title"], page=page))
    return view


for _key in PENDING:
    router.add_api_route(f"/{_key}", _pending_route(_key), methods=["GET"], include_in_schema=False)


# ---- JSON API used by the front-end ------------------------------------------------
@router.get("/api/dashboard")
async def api_dashboard(filters: Filters):
    return JSONResponse(analytics_service.build_dashboard(filters))


@router.get("/api/alerts")
async def api_alerts(filters: Filters):
    return JSONResponse(analytics_service.get_alerts(filters))


class RandomizeRequest(BaseModel):
    seed: int | None = Field(default=None, ge=0, le=999999)


@router.post("/api/randomize-demo")
async def api_randomize_demo(payload: RandomizeRequest | None = None):
    """Regenerate every sample metric with new random values. Your own drafts are kept."""
    seed = payload.seed if payload and payload.seed is not None else random.randint(1, 999999)
    get_store().randomize(seed)
    ai_service.clear_cache()            # cached AI answers describe the old data
    return {"ok": True, "seed": seed, "message": f"Data randomised (seed {seed})."}


@router.post("/api/reset-demo")
async def api_reset_demo():
    ai_service.clear_cache()
    get_store().reset()
    return {"ok": True, "message": "Demo data reset to its original state."}


# ---- Content library ---------------------------------------------------------------
@router.get("/content")
async def content_library(request: Request, filters: LibraryFilters):
    from urllib.parse import urlencode

    data = content_service.build_library(filters)
    base = {"days": filters.days, "platform": filters.platform, "campaign": filters.campaign,
            "q": filters.q, "format": filters.format, "topic": filters.topic,
            "status": filters.status, "sort": filters.sort}
    page_url = lambda n: "/content?" + urlencode({**base, "page": n})  # noqa: E731
    clear_url = "/content?" + urlencode({k: base[k] for k in ("days", "platform", "campaign")})
    return templates.TemplateResponse(
        request, "content.html",
        _ctx(request, filters, "content", "Content Library", lib=data, page_url=page_url,
             clear_url=clear_url, lf=filters, formats=data["formats"], campaigns=data["campaigns"],
             topics=data["topics"], min_date=data["today"], post=None))


@router.get("/content/{post_id}")
async def content_detail(request: Request, post_id: str, filters: Filters):
    detail = content_service.get_detail(post_id)
    if detail is None:
        return templates.TemplateResponse(
            request, "not_found.html",
            _ctx(request, filters, "content", "Post not found"), status_code=404)
    lib = content_service.build_library(ContentFilters())  # option lists for the edit form
    return templates.TemplateResponse(
        request, "post_detail.html",
        _ctx(request, filters, "content", "Post", d=detail, post=detail["full"],
             formats=lib["formats"], campaigns=lib["campaigns"], topics=lib["topics"],
             min_date=detail["today"]))


def _error(field: str, message: str, status: int = 422) -> JSONResponse:
    # Same shape as FastAPI's own validation errors so the front-end handles both identically.
    return JSONResponse({"detail": [{"loc": ["body", field], "msg": message}]}, status_code=status)


@router.post("/api/content/drafts", status_code=201)
async def api_create_draft(payload: DraftInput):
    try:
        post = content_service.create_draft(payload)
    except ContentValidationError as e:
        return _error(e.field, e.message)
    return {"id": post.id, "status": post.status}


@router.put("/api/content/{post_id}")
async def api_update_draft(post_id: str, payload: DraftInput):
    try:
        post = content_service.update_draft(post_id, payload)
    except ContentValidationError as e:
        return _error(e.field, e.message)
    except ContentNotFound:
        raise HTTPException(404, "Post not found.")
    except ContentLocked as e:
        raise HTTPException(409, str(e))
    return {"id": post.id, "status": post.status}


@router.delete("/api/content/{post_id}")
async def api_delete_draft(post_id: str):
    try:
        content_service.delete_draft(post_id)
    except ContentNotFound:
        raise HTTPException(404, "Post not found.")
    except ContentLocked as e:
        raise HTTPException(409, str(e))
    return {"ok": True}


# ---- AI assistant ------------------------------------------------------------------
SUGGESTIONS = [
    "Which content formats should we publish more of, and on which platforms?",
    "What changed in the last 7 days that I should look at?",
    "Which ad campaigns look weak, and what is the evidence?",
    "When is the best time to post on LinkedIn?",
    "Why is our overall engagement rate where it is? Explain the drivers.",
]


def _ai_error(e: AIUnavailable) -> JSONResponse:
    # The dashboard never depends on this: a failed AI call only affects the AI panel.
    body = {"error": {"kind": e.kind, "message": e.message, "retry_after": e.retry_after}}
    return JSONResponse(body, status_code=e.status)


@router.get("/assistant")
async def assistant_page(request: Request, filters: Filters):
    lib = content_service.build_library(ContentFilters())
    return templates.TemplateResponse(
        request, "ai_assistant.html",
        _ctx(request, filters, "assistant", "AI Assistant", ai=ai_service.status(), suggestions=SUGGESTIONS,
             topics=lib["topics"], formats=list(TYPE_LABELS.items()), objectives=OBJECTIVES, tones=TONES,
             campaign_names={c["id"]: c["name"] for c in lib["campaigns"]},
             min_date=lib["today"]))


@router.post("/api/assistant/ask")
async def api_assistant_ask(payload: AskRequest):
    try:
        return await assistant_service.ask(payload)
    except AIUnavailable as e:
        return _ai_error(e)


@router.post("/api/assistant/generate")
async def api_assistant_generate(payload: GenerateRequest):
    try:
        return await assistant_service.generate_post(payload)
    except AIUnavailable as e:
        return _ai_error(e)


@router.post("/api/assistant/save-draft", status_code=201)
async def api_assistant_save_draft(payload: DraftInput):
    """Saves an AI-generated post as a draft (or proposed post). Never publishes anything."""
    try:
        post = content_service.create_draft(payload, source="ai")
    except ContentValidationError as e:
        return _error(e.field, e.message)
    return {"id": post.id, "status": post.status}


@router.get("/api/ai/status")
async def api_ai_status():
    return await ai_service.check_connection()


# ---- AI recommendations ------------------------------------------------------------
@router.get("/recommendations")
async def recommendations_page(request: Request, filters: Filters):
    data = recommendation_service.page_data(filters.platform)
    return templates.TemplateResponse(
        request, "recommendations.html",
        _ctx(request, filters, "recommendations", "AI Recommendations", d=data, ai=ai_service.status()))


@router.post("/api/recommendations/generate")
async def api_generate_recommendations(payload: GenerateRecommendationsRequest):
    try:
        return await recommendation_service.generate(payload)
    except AIUnavailable as e:
        return _ai_error(e)


@router.post("/api/recommendations/{rec_id}/save", status_code=201)
async def api_save_recommendation(rec_id: str):
    """Saves the recommendation as a draft in the Content Library. Never publishes."""
    try:
        post = recommendation_service.save_as_draft(rec_id)
    except RecommendationNotFound:
        raise HTTPException(404, "Recommendation not found.")
    except RecommendationConflict as e:
        return JSONResponse({"detail": "Already saved as a draft.", "post_id": str(e)}, status_code=409)
    except ContentValidationError as e:
        return _error(e.field, e.message)
    return {"post_id": post.id}


@router.post("/api/recommendations/{rec_id}/{action}")
async def api_recommendation_status(rec_id: str, action: str):
    if action not in ("dismiss", "restore"):
        raise HTTPException(404, "Unknown action.")
    try:
        recommendation_service.set_status(rec_id, "dismissed" if action == "dismiss" else "new")
    except RecommendationNotFound:
        raise HTTPException(404, "Recommendation not found.")
    except RecommendationConflict:
        raise HTTPException(409, "Saved recommendations cannot be dismissed.")
    return {"ok": True}
