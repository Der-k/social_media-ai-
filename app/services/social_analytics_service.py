"""Social Analytics: organic performance by platform, format, topic and posting time.

Everything here is computed from the stored published posts through `services/metrics.py`, the
same source the dashboard uses, but limited to organic posts (no ad rows). Filters (date range,
platform, campaign) are applied by `analytics_repository`.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from app.repositories import analytics_repository as repo
from app.schemas.analytics import PLATFORMS, DashboardFilters, Post
from app.services import metrics as m
from app.services.analytics_service import _range as period

MIN_N = 3            # fewer posts than this is shown but marked thin
MIN_REACH = 1000     # same rule as the dashboard's best-performing list

KPI_DEFS = [
    # key, label, kind, sub-label
    ("posts", "Published posts", "int", "Organic"),
    ("reach", "Reach", "compact", "Sum of post reach"),
    ("impressions", "Impressions", "compact", "Organic"),
    ("engagements", "Engagements", "compact", "Likes, comments, shares, saves"),
    ("engagement_rate", "Engagement rate", "percent", "Engagements / reach"),
    ("avg_reach", "Average reach per post", "int", "Reach / posts"),
    ("link_clicks", "Link clicks", "int", "From organic posts"),
    ("active_share", "Saves and shares", "percent", "Share of all engagements"),
]
MIX = [("likes", "Likes"), ("comments", "Comments"), ("shares", "Shares"), ("saves", "Saves")]


def _kpis(posts: list[Post]) -> dict:
    a = m.aggregate_posts(posts)
    n = len(posts)
    return dict(
        posts=n, reach=a["reach"], impressions=a["impressions"], engagements=a["engagements"],
        engagement_rate=a["engagement_rate"], avg_reach=m.safe_div(a["reach"], n),
        link_clicks=a["link_clicks"], active_share=m.safe_div(a["saves"] + a["shares"], a["engagements"]),
        likes=a["likes"], comments=a["comments"], shares=a["shares"], saves=a["saves"])


def _mix(posts: list[Post]) -> dict | None:
    a = m.aggregate_posts(posts)
    if not a["engagements"]:
        return None
    return {k: a[k] / a["engagements"] * 100 for k, _ in MIX}


def _buckets(start: date, end: date, days: int) -> list[tuple[str, date, date]]:
    """Daily buckets for short ranges; otherwise 7-day buckets anchored on the last day, so the newest
    is always a full week. An older partial bucket is kept (so every post is counted) and labelled."""
    fmt = lambda d: d.strftime("%b %d").replace(" 0", " ")  # noqa: E731
    if days <= 14:
        return [(fmt(start + timedelta(days=i)), start + timedelta(days=i), start + timedelta(days=i)) for i in range(days)]
    out, hi = [], end
    while hi >= start:
        lo = max(start, hi - timedelta(days=6))
        span = (hi - lo).days + 1
        label = f"{fmt(lo)} - {fmt(hi)}" if lo != hi else fmt(lo)
        out.append((label + (f" ({span}d)" if span < 7 else ""), lo, hi))
        hi = lo - timedelta(days=1)
    return out[::-1]


def _pct(v: float | None, d: int = 2) -> float | None:
    return None if v is None else round(v * 100, d)


# --------------------------------------------------------------------------- #
def build_social(f: DashboardFilters) -> dict:
    start, end, prev_start, prev_end, has_prev = period(f)
    posts = repo.select_posts(f.platform, f.campaign, start, end)
    cur = _kpis(posts)
    prev = _kpis(repo.select_posts(f.platform, f.campaign, prev_start, prev_end)) if has_prev else None

    # ---- KPI cards with daily sparklines
    dates = [start + timedelta(days=i) for i in range(f.days)]
    by_day: dict[date, list[Post]] = defaultdict(list)
    for p in posts:
        by_day[p.published_at.date()].append(p)
    daily = [_kpis(by_day[d]) for d in dates]
    kpis = []
    for key, label, kind, sub in KPI_DEFS:
        delta = m.pct_change(cur[key], prev[key]) if prev else None
        kpis.append(dict(key=key, label=label, kind=kind, sub=sub, value=cur[key], delta=delta,
                         delta_good=None if delta is None or abs(delta) < 0.005 else delta > 0,
                         note="No posts in this range" if not posts else None,
                         spark=[d[key] for d in daily]))

    # ---- platform scorecards (ignore the platform filter so platforms can be compared)
    scorecards = []
    for pl in PLATFORMS:
        c = _kpis(repo.select_posts(pl, f.campaign, start, end))
        pv = _kpis(repo.select_posts(pl, f.campaign, prev_start, prev_end)) if has_prev else None
        scorecards.append(dict(platform=pl, posts=c["posts"], reach=c["reach"], er=c["engagement_rate"],
                               avg_reach=c["avg_reach"], saves_shares=c["active_share"],
                               ctr=m.safe_div(c["link_clicks"], c["reach"]),
                               er_delta=m.pct_change(c["engagement_rate"], pv["engagement_rate"]) if pv else None))

    # ---- trend and cadence
    buckets = _buckets(start, end, f.days)
    shown = [pl for pl in PLATFORMS if f.platform in ("all", pl)]
    trend = dict(labels=[b[0] for b in buckets], granularity="day" if f.days <= 14 else "week",
                 er={}, posts={}, overall_er=[])
    for pl in shown:
        er_row, n_row = [], []
        for _, lo, hi in buckets:
            ps = [p for p in posts if p.platform == pl and lo <= p.published_at.date() <= hi]
            er_row.append(_pct(m.aggregate_posts(ps)["engagement_rate"]))
            n_row.append(len(ps))
        trend["er"][pl], trend["posts"][pl] = er_row, n_row
    for _, lo, hi in buckets:
        trend["overall_er"].append(_pct(m.aggregate_posts([p for p in posts if lo <= p.published_at.date() <= hi])["engagement_rate"]))

    # ---- engagement mix
    mix_platform = [dict(label=pl, n=len(ps), **(_mix(ps) or {})) for pl in shown
                    for ps in [[p for p in posts if p.platform == pl]] if ps]
    by_fmt = defaultdict(list)
    for p in posts:
        by_fmt[p.content_type].append(p)
    mix_format = [dict(label=m.TYPE_LABELS[k], n=len(v), **(_mix(v) or {})) for k, v in
                  sorted(by_fmt.items(), key=lambda kv: -len(kv[1])) if _mix(v)]

    # ---- format and topic tables
    overall_er = cur["engagement_rate"]
    def rows(stats: dict, label) -> list[dict]:
        return [dict(key=k, label=label(k), n=s["n"], thin=s["n"] < MIN_N, er=s["er"], lift=m.safe_div(s["er"], overall_er),
                     avg_reach=s["avg_reach"], saves_pp=s["saves_pp"], shares_pp=s["shares_pp"],
                     comments_pp=s["comments_pp"], clicks_pp=s["clicks_pp"]) for k, s in stats.items()]
    formats = sorted(rows(m.group_stats(posts, lambda p: p.content_type), lambda k: m.TYPE_LABELS[k]),
                     key=lambda r: -(r["er"] or 0))
    topics = sorted((r for r in rows(m.group_stats(posts, lambda p: p.topic), lambda k: k) if r["n"] >= 2),
                    key=lambda r: -(r["er"] or 0))

    # ---- platform x format matrix (engagement vs that platform's own average)
    matrix = []
    plat_er = {pl: m.aggregate_posts([p for p in posts if p.platform == pl])["engagement_rate"] for pl in PLATFORMS}
    cell = m.group_stats(posts, lambda p: (p.platform, p.content_type))
    for fmt, label in m.TYPE_LABELS.items():
        matrix.append(dict(label=label, cells=[
            dict(platform=pl, n=cell[(pl, fmt)]["n"], er=cell[(pl, fmt)]["er"],
                 lift=m.safe_div(cell[(pl, fmt)]["er"], plat_er[pl])) if (pl, fmt) in cell
            else dict(platform=pl, n=0, er=None, lift=None) for pl in PLATFORMS]))

    # ---- posting time (all history for the platform/campaign filters; ranges are too thin otherwise)
    hist = repo.select_posts(f.platform, f.campaign)
    heat = _heatmap(hist)
    windows = [_window(pl, repo.select_posts(pl, f.campaign)) for pl in PLATFORMS]

    # ---- scatter: every post's reach against its engagement rate
    scatter = [dict(x=p.reach, y=_pct(p.engagement_rate), platform=p.platform, id=p.id,
                    caption=" ".join(p.caption.split())[:90], type=m.TYPE_LABELS[p.content_type],
                    date=p.published_at.date().isoformat())
               for p in posts if p.reach and p.engagement_rate is not None]

    return dict(
        meta=dict(start=start.isoformat(), end=end.isoformat(), days=f.days, has_prev=has_prev, platform=f.platform,
                  campaign=f.campaign, posts=len(posts), as_of=end.isoformat(), demo=True,
                  mean_reach=cur["avg_reach"], mean_er=_pct(overall_er)),
        kpis=kpis, scorecards=scorecards, trend=trend, mix=dict(platform=mix_platform, format=mix_format),
        formats=formats, topics=topics, matrix=matrix, heatmap=heat, windows=windows, scatter=scatter,
        insights=_insights(posts, cur, formats, topics, heat, scorecards, f))


def _heatmap(posts: list[Post]) -> dict:
    grid = [[[] for _ in m.DAYPARTS] for _ in range(7)]
    for p in posts:
        di = m.daypart_index(p.published_at.hour)
        if di is not None:
            grid[p.published_at.weekday()][di].append(p)
    cells = []
    for row in grid:
        out = []
        for ps in row:
            a = m.aggregate_posts(ps)
            out.append(dict(n=len(ps), er=a["engagement_rate"], avg_reach=a["reach"] / len(ps) if ps else None))
        cells.append(out)
    best = {}
    for metric in ("er", "avg_reach"):
        for min_n in (MIN_N, 2):
            cand = [(cells[w][d][metric], w, d) for w in range(7) for d in range(len(m.DAYPARTS))
                    if cells[w][d]["n"] >= min_n and cells[w][d][metric] is not None]
            if cand:
                _, w, d = max(cand)
                best[metric] = dict(weekday=w, daypart=d, label=f"{m.WEEKDAYS_LONG[w]}, {m.daypart_label(d)}", n=cells[w][d]["n"])
                break
    return dict(days=m.WEEKDAYS, dayparts=[n for n, _, _ in m.DAYPARTS], ranges=[f"{lo:02d}-{hi % 24:02d}" for _, lo, hi in m.DAYPARTS],
                cells=cells, best=best, total=len(posts))


def _window(platform: str, posts: list[Post]) -> dict:
    parts = m.group_stats(posts, lambda p: m.daypart_index(p.published_at.hour))
    days = m.group_stats(posts, lambda p: p.published_at.weekday())
    p_best = max(((i, s) for i, s in parts.items() if i is not None and s["n"] >= MIN_N), key=lambda kv: kv[1]["er"], default=None)
    d_best = max(((d, s) for d, s in days.items() if s["n"] >= MIN_N), key=lambda kv: kv[1]["er"], default=None)
    return dict(platform=platform, posts=len(posts),
                daypart=dict(label=m.daypart_label(p_best[0]), er=p_best[1]["er"], n=p_best[1]["n"]) if p_best else None,
                weekday=dict(label=m.WEEKDAYS_LONG[d_best[0]], er=d_best[1]["er"], n=d_best[1]["n"]) if d_best else None)


def _insights(posts, cur, formats, topics, heat, scorecards, f) -> list[dict]:
    out: list[dict] = []
    if not posts:
        return [dict(tone="info", title="No posts in this range", detail="Widen the date range or clear a filter.")]
    ok = [r for r in formats if not r["thin"] and r["er"] is not None]
    if len(ok) >= 2:
        b = max(ok, key=lambda r: r["er"])
        out.append(dict(tone="good", title=f"{b['label']} has the highest engagement rate",
                        detail=f"{b['er']:.1%} across {b['n']} posts, {b['lift'] - 1:+.0%} vs the {cur['engagement_rate']:.1%} average."))
        s = max(ok, key=lambda r: r["saves_pp"])
        out.append(dict(tone="good", title=f"{s['label']} earns the most saves per post",
                        detail=f"{s['saves_pp']:.0f} saves per post and {s['shares_pp']:.0f} shares, across {s['n']} posts."))
        w = max(ok, key=lambda r: r["avg_reach"])
        out.append(dict(tone="good", title=f"{w['label']} reaches the most people",
                        detail=f"{w['avg_reach']:,.0f} average reach per post vs {cur['avg_reach']:,.0f} overall."))
        lo = min(ok, key=lambda r: r["er"])
        if lo["key"] != b["key"] and lo["lift"] is not None and lo["lift"] < 0.9:
            out.append(dict(tone="bad", title=f"{lo['label']} lags the average",
                            detail=f"{lo['er']:.1%} engagement across {lo['n']} posts, {lo['lift'] - 1:+.0%} vs average."))
    tk = [t for t in topics if not t["thin"]]
    if len(tk) >= 2:
        out.append(dict(tone="good", title=f"'{tk[0]['label']}' is the strongest topic",
                        detail=f"{tk[0]['er']:.1%} engagement across {tk[0]['n']} posts. Weakest: '{tk[-1]['label']}' at {tk[-1]['er']:.1%}."))
    if cur["active_share"] is not None:
        out.append(dict(tone="info", title="Saves and shares signal deeper interest",
                        detail=f"They make up {cur['active_share']:.0%} of engagements ({cur['saves'] + cur['shares']:,} of {cur['engagements']:,})."))
    best = heat["best"].get("er")
    if best:
        out.append(dict(tone="good", title=f"Strongest posting slot: {best['label']}",
                        detail=f"Highest engagement rate in the history, from {best['n']} posts. Filter by platform for a cleaner read."
                        if f.platform == "all" else f"Highest {f.platform} engagement rate in the history, from {best['n']} posts."))
    active = [s for s in scorecards if s["posts"] >= MIN_N and s["er"] is not None]
    if f.platform == "all" and len(active) >= 2:
        t = max(active, key=lambda s: s["er"])
        out.append(dict(tone="info", title=f"{t['platform']} leads on engagement rate",
                        detail=f"{t['er']:.1%} across {t['posts']} posts, with {t['reach']:,} total reach."))
    return out[:8]
