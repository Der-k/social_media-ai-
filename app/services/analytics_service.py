"""Builds the dashboard payload from the single underlying dataset.

Every number on the dashboard (KPI cards, charts, insights) comes from the same
filtered posts and ad rows, via the functions in `metrics`.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta

from app.repositories import analytics_repository as repo
from app.schemas.analytics import PLATFORMS, DashboardFilters
from app.services import metrics as m

KPI_DEFS = [
    # key, label, kind, sub-label, higher_is_better (None = neutral)
    ("reach", "Total reach", "compact", "Organic + paid", True),
    ("impressions", "Impressions", "compact", "Organic + paid", True),
    ("engagement_rate", "Engagement rate", "percent", "Organic posts", True),
    ("link_clicks", "Link clicks", "int", "Organic + paid", True),
    ("spend", "Advertising spend", "money0", "Paid campaigns", None),
    ("conversions", "Conversions", "int", "Paid campaigns", True),
    ("cpc", "Cost per click", "money2", "Spend / paid clicks", False),
    ("roas", "ROAS", "ratio", "Revenue / spend", True),
]
KPI_LABEL = {k: label for k, label, *_ in KPI_DEFS}


def _fmt(kind: str, v: float) -> str:
    return {
        "compact": m.fmt_compact, "int": lambda x: f"{x:,.0f}",
        "percent": lambda x: f"{x:.1%}", "money0": lambda x: m.fmt_money(x, 0),
        "money2": m.fmt_money, "ratio": lambda x: f"{x:.2f}x",
    }[kind](v)


def _range(f: DashboardFilters):
    end = repo.as_of()
    start = end - timedelta(days=f.days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=f.days - 1)
    has_prev = prev_start >= repo.first_date()
    return start, end, prev_start, prev_end, has_prev


def _rel(d: date, today: date) -> str:
    n = (today - d).days
    return "today" if n <= 0 else "yesterday" if n == 1 else f"{n} days ago"


def _missing_note(key: str, k: dict) -> str | None:
    paid = k["paid"]
    if key == "conversions" and k["conversions"] is None:
        return "Not tracked for these campaigns" if paid["rows"] else "No ad activity in range"
    if key == "cpc" and k["cpc"] is None:
        return "No paid clicks in range"
    if key == "roas" and k["roas"] is None:
        return "Revenue not tracked" if paid["rows"] else "No ad activity in range"
    if key == "engagement_rate" and k["engagement_rate"] is None:
        return "No posts in range"
    return None


# --------------------------------------------------------------------------- #
def build_dashboard(f: DashboardFilters) -> dict:
    start, end, prev_start, prev_end, has_prev = _range(f)
    today = repo.as_of()

    posts = repo.select_posts(f.platform, f.campaign, start, end)
    rows = repo.select_ad_rows(f.platform, f.campaign, start, end)
    cur = m.combined_kpis(posts, rows)
    prev = None
    if has_prev:
        prev = m.combined_kpis(repo.select_posts(f.platform, f.campaign, prev_start, prev_end),
                               repo.select_ad_rows(f.platform, f.campaign, prev_start, prev_end))

    # ---- daily series --------------------------------------------------- #
    dates = [start + timedelta(days=i) for i in range(f.days)]
    pby, rby = defaultdict(list), defaultdict(list)
    for p in posts:
        pby[p.published_at.date()].append(p)
    for r in rows:
        rby[r.date].append(r)
    daily = [m.combined_kpis(pby[d], rby[d]) for d in dates]
    series = {
        "labels": [d.strftime("%b %d").replace(" 0", " ") for d in dates],
        "dates": [d.isoformat() for d in dates],
        "engagements": [k["engagements"] for k in daily],
        "engagement_rate": [None if k["engagement_rate"] is None else round(k["engagement_rate"] * 100, 2) for k in daily],
        "reach": [k["reach"] for k in daily],
        "impressions": [k["impressions"] for k in daily],
        "spend": [k["spend"] for k in daily],
        "conversions": [k["conversions"] for k in daily],
    }
    spark_src = {key: [k[key] for k in daily] for key, *_ in KPI_DEFS}
    # Daily ROAS / CPC can be undefined on quiet days; the front-end skips None.

    # ---- KPI cards ------------------------------------------------------ #
    kpis = []
    for key, label, kind, sub, higher_good in KPI_DEFS:
        delta = m.pct_change(cur[key], prev[key]) if prev else None
        good = None
        if delta is not None and higher_good is not None and abs(delta) >= 0.005:
            good = (delta > 0) == higher_good
        kpis.append(dict(key=key, label=label, kind=kind, sub=sub, value=cur[key],
                         delta=delta, delta_good=good, note=_missing_note(key, cur),
                         spark=spark_src[key]))

    # ---- platform comparison (ignores the platform filter on purpose) ---- #
    platforms = []
    for pl in PLATFORMS:
        k = m.combined_kpis(repo.select_posts(pl, f.campaign, start, end),
                            repo.select_ad_rows(pl, f.campaign, start, end))
        platforms.append(dict(platform=pl, reach=k["reach"], engagement_rate=k["engagement_rate"],
                              posts=k["organic"]["posts"], spend=k["spend"], conversions=k["conversions"]))

    # ---- best content --------------------------------------------------- #
    ranked = sorted((p for p in posts if (p.reach or 0) >= 1000 and p.engagement_rate is not None),
                    key=lambda p: p.engagement_rate, reverse=True)[:6]
    top_posts = [dict(
        id=p.id, caption=p.caption, platform=p.platform, content_type=p.content_type,
        type_label=m.TYPE_LABELS[p.content_type], topic=p.topic,
        label=f"{m.PLATFORM_SHORT[p.platform]} {m.TYPE_LABELS[p.content_type].lower()}: {p.topic.lower()}",
        published=p.published_at.date().isoformat(), reach=p.reach, engagements=p.engagements,
        engagement_rate=round(p.engagement_rate * 100, 2)) for p in ranked]

    heatmap = _heatmap(repo.select_posts(f.platform, f.campaign))
    changes = _changes(f, cur, prev, has_prev, end)
    signals = _signals(posts, heatmap)
    activity = _activity(f, today)

    campaigns = repo.select_campaigns()
    camp_name = next((c.name for c in campaigns if c.id == f.campaign), None)
    return dict(
        meta=dict(as_of=end.isoformat(), start=start.isoformat(), end=end.isoformat(), days=f.days,
                  has_prev=has_prev, prev_start=prev_start.isoformat(), platform=f.platform,
                  campaign=f.campaign, campaign_name=camp_name, demo=True,
                  generated_at=datetime.now().isoformat(timespec="seconds"),
                  post_count=len(posts), ad_row_count=len(rows)),
        kpis=kpis, series=series, platforms=platforms, top_posts=top_posts, heatmap=heatmap,
        changes=changes, signals=signals, activity=activity,
        options=dict(campaigns=[dict(id=c.id, name=c.name, platform=c.platform, status=c.status)
                                for c in campaigns]),
    )


def get_alerts(f: DashboardFilters) -> list[dict]:
    """Notable changes only, for the notification bell."""
    start, end, prev_start, prev_end, has_prev = _range(f)
    cur = m.combined_kpis(repo.select_posts(f.platform, f.campaign, start, end),
                          repo.select_ad_rows(f.platform, f.campaign, start, end))
    prev = None
    if has_prev:
        prev = m.combined_kpis(repo.select_posts(f.platform, f.campaign, prev_start, prev_end),
                               repo.select_ad_rows(f.platform, f.campaign, prev_start, prev_end))
    return _changes(f, cur, prev, has_prev, end)


# --------------------------------------------------------------------------- #
def _heatmap(posts) -> dict:
    """Engagement rate by weekday x daypart, from all history for the filters."""
    cells = [[dict(eng=0, reach=0, n=0) for _ in m.DAYPARTS] for _ in range(7)]
    for p in posts:
        if p.reach is None or p.engagements is None:
            continue
        di = m.daypart_index(p.published_at.hour)
        if di is None:
            continue
        c = cells[p.published_at.weekday()][di]
        c["eng"] += p.engagements
        c["reach"] += p.reach
        c["n"] += 1
    out = [[dict(er=m.safe_div(c["eng"], c["reach"]), n=c["n"]) for c in row] for row in cells]
    best = None
    for min_n in (3, 2):
        cand = [(out[w][d]["er"], w, d) for w in range(7) for d in range(len(m.DAYPARTS))
                if out[w][d]["n"] >= min_n and out[w][d]["er"] is not None]
        if cand:
            er, w, d = max(cand)
            best = dict(weekday=w, daypart=d, er=er, n=out[w][d]["n"], day_name=m.WEEKDAYS_LONG[w],
                        daypart_label=m.daypart_label(d))
            break
    return dict(days=m.WEEKDAYS, dayparts=[f"{n}" for n, _, _ in m.DAYPARTS],
                ranges=[f"{lo:02d}-{hi % 24:02d}" for _, lo, hi in m.DAYPARTS],
                cells=out, best=best, total_posts=len(posts),
                basis="All available history (90 days) so each cell has more posts.")


def _signals(posts, heatmap) -> list[dict]:
    groups = defaultdict(list)
    for p in posts:
        groups[p.content_type].append(p)
    stats = []
    for ctype, ps in groups.items():
        a = m.aggregate_posts(ps)
        if a["posts"] >= 3 and a["engagement_rate"] is not None:
            stats.append((ctype, a))
    sig = []
    if len(stats) >= 2:
        best = max(stats, key=lambda s: s[1]["engagement_rate"])
        wide = max(stats, key=lambda s: s[1]["reach"] / s[1]["posts"])
        weak = min(stats, key=lambda s: s[1]["engagement_rate"])
        sig.append(dict(label="Highest engagement", tone="good", value=m.TYPE_LABELS[best[0]],
                        detail=f"{best[1]['engagement_rate']:.1%} engagement rate across {best[1]['posts']} posts"))
        sig.append(dict(label="Widest reach per post", tone="good", value=m.TYPE_LABELS[wide[0]],
                        detail=f"{m.fmt_compact(wide[1]['reach'] / wide[1]['posts'])} average reach, {wide[1]['posts']} posts"))
        sig.append(dict(label="Lowest engagement", tone="bad", value=m.TYPE_LABELS[weak[0]],
                        detail=f"{weak[1]['engagement_rate']:.1%} engagement rate across {weak[1]['posts']} posts"))
    else:
        sig.append(dict(label="Format comparison", tone="info", value="Not enough data",
                        detail="Needs at least 3 posts in two or more formats in this range."))
    b = heatmap["best"]
    if b:
        sig.append(dict(label="Strongest posting window", tone="good",
                        value=f"{b['day_name']}, {b['daypart_label'].split(' ')[0].lower()}",
                        detail=f"{b['er']:.1%} engagement rate across {b['n']} posts"))
    else:
        sig.append(dict(label="Strongest posting window", tone="info", value="Not enough data",
                        detail="Needs at least 2 posts in a time slot."))
    return sig


def _changes(f: DashboardFilters, cur: dict, prev: dict | None, has_prev: bool, end: date) -> list[dict]:
    items: list[dict] = []
    # 1) Headline KPI moves versus the previous period.
    if prev:
        for key, label, kind, _, higher_good in KPI_DEFS:
            d = m.pct_change(cur[key], prev[key])
            if d is None or abs(d) < 0.10:
                continue
            sev = "info" if higher_good is None else ("good" if (d > 0) == higher_good else "bad")
            items.append(dict(
                severity=sev, weight=abs(d),
                title=f"{label} {'up' if d > 0 else 'down'} {abs(d):.0%} vs previous {f.days} days",
                detail=f"{_fmt(kind, prev[key])} to {_fmt(kind, cur[key])}."))
    # 2) Campaign-level movement over the last 7 days, and budget pace.
    for c in repo.select_campaigns(f.platform, f.campaign):
        if c.status == "completed":
            continue
        all_rows = [r for r in repo.select_ad_rows(campaign=c.id)]
        last7 = m.aggregate_ads([r for r in all_rows if end - timedelta(days=6) <= r.date <= end])
        prior7 = m.aggregate_ads([r for r in all_rows if end - timedelta(days=13) <= r.date <= end - timedelta(days=7)])
        total = m.aggregate_ads(all_rows)
        if c.status == "active" and last7["rows"] >= 5 and prior7["rows"] >= 5:
            d = m.pct_change(last7["cpc"], prior7["cpc"])
            if d is not None and d >= 0.20:
                items.append(dict(severity="bad", weight=d, campaign_id=c.id,
                                  title=f"{c.name}: cost per click up {d:.0%} in 7 days",
                                  detail=f"{m.fmt_money(prior7['cpc'])} to {m.fmt_money(last7['cpc'])} on {c.platform}."))
            d = m.pct_change(last7["roas"], prior7["roas"])
            if d is not None and abs(d) >= 0.20:
                items.append(dict(severity="good" if d > 0 else "bad", weight=abs(d), campaign_id=c.id,
                                  title=f"{c.name}: ROAS {'up' if d > 0 else 'down'} {abs(d):.0%} in 7 days",
                                  detail=f"{prior7['roas']:.2f}x to {last7['roas']:.2f}x over the last 7 days."))
        if c.status == "active" and c.budget:
            used = total["spend"] / c.budget
            left = (c.planned_end_date - end).days
            if used >= 0.85:
                items.append(dict(severity="info", weight=used, campaign_id=c.id,
                                  title=f"{c.name} has used {used:.0%} of its budget",
                                  detail=f"{m.fmt_money(total['spend'], 0)} of {m.fmt_money(c.budget, 0)} spent, {max(left, 0)} days until the planned end."))
        if total["roas"] is not None and total["roas"] < 1.0 and total["spend"] > 500:
            items.append(dict(severity="bad", weight=1.0 - total["roas"], campaign_id=c.id,
                              title=f"{c.name} returns less than it spends",
                              detail=f"Lifetime ROAS {total['roas']:.2f}x on {m.fmt_money(total['spend'], 0)} spend. Status: {c.status}."))
    order = {"bad": 0, "info": 1, "good": 2}
    items.sort(key=lambda i: (order[i["severity"]], -i["weight"]))
    for i in items:
        i.pop("weight", None)
    return items[:7]


def _activity(f: DashboardFilters, today: date) -> list[dict]:
    from app.repositories import content_repository

    ev: list[tuple[datetime, dict]] = []
    for p in content_repository.list_posts():
        if f.platform != "all" and p.platform != f.platform:
            continue
        if f.campaign != "all" and p.campaign_id != f.campaign:
            continue
        if p.status == "published":
            er = f" - {p.engagement_rate:.1%} engagement" if p.engagement_rate is not None else ""
            ev.append((p.published_at, dict(kind="post", platform=p.platform,
                       title=f"{m.TYPE_LABELS[p.content_type]} published on {p.platform}",
                       detail=p.caption[:96] + ("..." if len(p.caption) > 96 else "") + er)))
        elif p.status == "proposed":
            ev.append((p.created_at, dict(kind="proposal", platform=p.platform,
                       title=f"Post proposed for {p.scheduled_for:%b %d}".replace(" 0", " "),
                       detail=p.caption[:96])))
        else:
            ev.append((p.created_at, dict(kind="draft", platform=p.platform,
                       title=f"Draft saved for {p.platform}", detail=p.caption[:96])))
    for c in repo.select_campaigns(f.platform, f.campaign):
        rows = repo.select_ad_rows(campaign=c.id)
        ev.append((datetime.combine(c.start_date, datetime.min.time()),
                   dict(kind="campaign", platform=c.platform, title=f"Campaign launched: {c.name}",
                        detail=f"{c.objective} objective, {m.fmt_money(c.budget, 0)} budget.")))
        if c.status != "active" and rows:
            last = max(r.date for r in rows)
            ev.append((datetime.combine(last, datetime.min.time()),
                       dict(kind="campaign", platform=c.platform,
                            title=f"Campaign {c.status}: {c.name}", detail=f"Last spend recorded {last:%b %d}.".replace(" 0", " "))))
    ev.sort(key=lambda e: e[0], reverse=True)
    out = []
    for ts, e in ev[:8]:
        e["when"] = _rel(ts.date(), today) + (f", {ts:%H:%M}" if ts.hour or ts.minute else "")
        out.append(e)
    return out
