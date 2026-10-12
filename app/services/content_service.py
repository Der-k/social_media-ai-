"""Content library logic: filtering, sorting, best/worst posts, benchmarks, draft CRUD.

Published-post performance always comes from the same stored metrics used by the
dashboard. Drafts and proposed posts carry no metrics (None), so they never
affect any average.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from app.repositories import analytics_repository as repo
from app.repositories import campaign_repository, content_repository
from app.schemas.analytics import Post
from app.schemas.content import ContentFilters, DraftInput
from app.services import metrics as m

PER_PAGE = 15
MIN_REACH = 1000      # same threshold the dashboard uses for "best-performing"
MIN_PEERS = 3         # fewer similar posts than this is not a benchmark
STRONG, WEAK = 1.25, 0.75


class ContentValidationError(Exception):
    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field, self.message = field, message


class ContentNotFound(Exception):
    pass


class ContentLocked(Exception):
    """Raised when someone tries to edit or delete a published post."""


# --------------------------------------------------------------------------- #
def _when(p: Post) -> datetime:
    return p.published_at or p.scheduled_for or p.created_at


def _platform_baseline(published: list[Post]) -> dict[str, float | None]:
    return {pl: m.aggregate_posts([p for p in published if p.platform == pl])["engagement_rate"]
            for pl in {p.platform for p in published}}


def _tier(p: Post, baseline: dict) -> str | None:
    """strong / typical / weak relative to the platform's own average. None if not rated."""
    base = baseline.get(p.platform)
    if p.status != "published" or (p.reach or 0) < MIN_REACH or p.engagement_rate is None or not base:
        return None
    ratio = p.engagement_rate / base
    return "strong" if ratio >= STRONG else "weak" if ratio <= WEAK else "typical"


def _date_info(p: Post) -> tuple[str, str]:
    if p.status == "published":
        return f"{p.published_at:%b %d, %H:%M}".replace(" 0", " "), "published"
    if p.scheduled_for:
        return f"{p.scheduled_for:%b %d, %H:%M}".replace(" 0", " "), "planned"
    return f"Created {p.created_at:%b %d}".replace(" 0", " "), "created"


def _row(p: Post, baseline: dict, camp_names: dict) -> dict:
    label, kind = _date_info(p)
    return dict(
        id=p.id, caption=p.caption, platform=p.platform, content_type=p.content_type,
        type_label=m.TYPE_LABELS[p.content_type], topic=p.topic, status=p.status,
        date_label=label, date_kind=kind, reach=p.reach, impressions=p.impressions,
        likes=p.likes, comments=p.comments, shares=p.shares, saves=p.saves,
        link_clicks=p.link_clicks, er=p.engagement_rate, campaign_id=p.campaign_id,
        campaign_name=camp_names.get(p.campaign_id), tier=_tier(p, baseline), source=p.source,
    )


def _sort_key(sort: str):
    num = {"er_desc": lambda p: p.engagement_rate, "er_asc": lambda p: p.engagement_rate,
           "reach_desc": lambda p: p.reach, "clicks_desc": lambda p: p.link_clicks}
    return num.get(sort)


def _sorted(posts: list[Post], sort: str) -> list[Post]:
    if sort in ("newest", "oldest"):
        return sorted(posts, key=_when, reverse=(sort == "newest"))
    getter = _sort_key(sort)
    have = [p for p in posts if getter(p) is not None]
    missing = [p for p in posts if getter(p) is None]          # unpublished posts always last
    have.sort(key=getter, reverse=(sort != "er_asc"))
    return have + sorted(missing, key=_when, reverse=True)


# --------------------------------------------------------------------------- #
def build_library(f: ContentFilters) -> dict:
    end = repo.as_of()
    start = end - timedelta(days=f.days - 1)
    all_posts = content_repository.list_posts()
    published_all = [p for p in all_posts if p.status == "published"]
    baseline = _platform_baseline(published_all)
    camp_names = {c.id: c.name for c in campaign_repository.list_campaigns()}

    def in_scope(p: Post) -> bool:
        if f.platform != "all" and p.platform != f.platform:
            return False
        if f.campaign != "all" and p.campaign_id != f.campaign:
            return False
        if p.status == "published" and not (start <= p.published_at.date() <= end):
            return False
        return True

    scoped = [p for p in all_posts if in_scope(p)]
    scoped_pub = [p for p in scoped if p.status == "published"]
    rated = [p for p in scoped_pub if (p.reach or 0) >= MIN_REACH and p.engagement_rate is not None]
    rated.sort(key=lambda p: p.engagement_rate, reverse=True)
    # Never show the same post as both best and worst when there are few posts.
    k = min(5, len(rated) // 2)
    best = rated[:k] if k else rated[:1]
    worst = rated[-k:][::-1] if k else []

    tokens = f.q.lower().split()
    def matches(p: Post) -> bool:
        if f.format != "all" and p.content_type != f.format:
            return False
        if f.topic != "all" and p.topic != f.topic:
            return False
        if f.status != "all" and p.status != f.status:
            return False
        hay = f"{p.caption} {p.topic} {m.TYPE_LABELS[p.content_type]} {p.platform}".lower()
        return all(t in hay for t in tokens)

    filtered = _sorted([p for p in scoped if matches(p)], f.sort)
    pages = max(1, math.ceil(len(filtered) / PER_PAGE))
    page = min(f.page, pages)
    chunk = filtered[(page - 1) * PER_PAGE: page * PER_PAGE]

    agg = m.aggregate_posts(scoped_pub)
    return dict(
        rows=[_row(p, baseline, camp_names) for p in chunk],
        best=[_row(p, baseline, camp_names) for p in best],
        worst=[_row(p, baseline, camp_names) for p in worst],
        total=len(filtered), page=page, pages=pages,
        first=(page - 1) * PER_PAGE + 1 if filtered else 0, last=min(page * PER_PAGE, len(filtered)),
        summary=dict(published=len(scoped_pub), drafts=sum(p.status == "draft" for p in scoped),
                     proposed=sum(p.status == "proposed" for p in scoped), er=agg["engagement_rate"],
                     rated=len(rated)),
        topics=sorted({p.topic for p in all_posts}),
        formats=[(k, v) for k, v in m.TYPE_LABELS.items()],
        campaigns=[dict(id=c.id, name=c.name, platform=c.platform) for c in campaign_repository.list_campaigns()],
        range=dict(start=start.isoformat(), end=end.isoformat()),
        today=end.isoformat(), min_reach=MIN_REACH,
    )


# --------------------------------------------------------------------------- #
def _bench(peers: list[Post]) -> dict:
    n = len(peers)
    agg = m.aggregate_posts(peers)
    per = lambda key: (agg[key] / n) if n else None  # noqa: E731
    return dict(n=n, thin=n < MIN_PEERS, engagement_rate=agg["engagement_rate"], reach=per("reach"),
                saves=per("saves"), shares=per("shares"), comments=per("comments"),
                link_clicks=per("link_clicks"))


METRIC_ROWS = [("engagement_rate", "Engagement rate", "pct"), ("reach", "Reach", "num"),
               ("saves", "Saves", "num"), ("shares", "Shares", "num"),
               ("comments", "Comments", "num"), ("link_clicks", "Link clicks", "num")]


def get_detail(post_id: str) -> dict | None:
    p = content_repository.get_post(post_id)
    if p is None:
        return None
    all_posts = content_repository.list_posts()
    published = [x for x in all_posts if x.status == "published"]
    baseline = _platform_baseline(published)
    camp_names = {c.id: c.name for c in campaign_repository.list_campaigns()}
    peers = [x for x in published if x.id != p.id]
    plat = [x for x in peers if x.platform == p.platform]
    fmt = [x for x in plat if x.content_type == p.content_type]
    b_plat, b_fmt = _bench(plat), _bench(fmt)

    is_pub = p.status == "published"
    values = dict(engagement_rate=p.engagement_rate, reach=p.reach, saves=p.saves, shares=p.shares,
                  comments=p.comments, link_clicks=p.link_clicks)
    rows = []
    for key, label, kind in METRIC_ROWS:
        v = values[key]
        d_plat = None if (b_plat["thin"] or not is_pub) else m.pct_change(v, b_plat[key])
        d_fmt = None if (b_fmt["thin"] or not is_pub) else m.pct_change(v, b_fmt[key])
        rows.append(dict(key=key, label=label, kind=kind, value=v, platform=b_plat[key], format=b_fmt[key],
                         d_platform=d_plat, d_format=d_fmt))

    timing = None
    stamp = p.published_at or p.scheduled_for
    if stamp:
        di = m.daypart_index(stamp.hour)
        timing = dict(weekday=m.WEEKDAYS_LONG[stamp.weekday()], time=f"{stamp:%H:%M}",
                      daypart=m.daypart_label(di) if di is not None else None)

    similar = sorted((x for x in fmt if x.engagement_rate is not None),
                     key=lambda x: x.engagement_rate, reverse=True)[:3]
    return dict(
        post=_row(p, baseline, camp_names), full=p, is_published=is_pub,
        editable=not is_pub, scheduled_input=p.scheduled_for.strftime("%Y-%m-%dT%H:%M") if p.scheduled_for else "",
        engagements=p.engagements, bench_rows=rows, b_platform=b_plat, b_format=b_fmt,
        timing=timing, similar=[_row(x, baseline, camp_names) for x in similar],
        campaign=next((dict(id=c.id, name=c.name, platform=c.platform, objective=c.objective, status=c.status)
                       for c in campaign_repository.list_campaigns() if c.id == p.campaign_id), None),
        today=repo.as_of().isoformat(),
    )


# --------------------------------------------------------------------------- #
def _validate(d: DraftInput) -> None:
    if d.status == "proposed" and d.scheduled_for is None:
        raise ContentValidationError("scheduled_for", "Choose a date and time for a proposed post.")
    if d.scheduled_for and d.scheduled_for.date() < repo.as_of():
        raise ContentValidationError("scheduled_for", f"Choose a date on or after {repo.as_of():%b %d, %Y}.".replace(" 0", " "))
    if d.campaign_id:
        camp = campaign_repository.get_campaign(d.campaign_id)
        if camp is None:
            raise ContentValidationError("campaign_id", "That campaign does not exist.")
        if camp.platform != d.platform:
            raise ContentValidationError("campaign_id", f"{camp.name} runs on {camp.platform}. Pick a campaign on {d.platform} or none.")


def create_draft(d: DraftInput, source: str = "manual") -> Post:
    _validate(d)
    # "Today" in the demo is the dataset's as-of date, not the real clock date.
    created = datetime.combine(repo.as_of(), datetime.now().time()).replace(microsecond=0)
    post = Post(id=content_repository.next_post_id(), caption=d.caption, platform=d.platform,
                content_type=d.content_type, topic=d.topic, status=d.status, created_at=created,
                scheduled_for=d.scheduled_for, campaign_id=d.campaign_id, source=source)
    return content_repository.add_post(post)


def update_draft(post_id: str, d: DraftInput) -> Post:
    existing = content_repository.get_post(post_id)
    if existing is None:
        raise ContentNotFound(post_id)
    if existing.status == "published":
        raise ContentLocked("Published posts cannot be edited.")
    _validate(d)
    updated = content_repository.update_post(
        post_id, caption=d.caption, platform=d.platform, content_type=d.content_type, topic=d.topic,
        status=d.status, scheduled_for=d.scheduled_for.isoformat() if d.scheduled_for else None,
        campaign_id=d.campaign_id)
    return updated


def delete_draft(post_id: str) -> None:
    existing = content_repository.get_post(post_id)
    if existing is None:
        raise ContentNotFound(post_id)
    if existing.status == "published":
        raise ContentLocked("Published posts cannot be deleted.")
    content_repository.delete_post(post_id)
