"""Deterministic metric calculations. No I/O, no AI.

Conventions used across the app:
  * `None` means "not available / not tracked / undefined", never zero.
  * A real zero (e.g. 0 conversions on a tracked campaign) stays 0.
  * Ratios return None when the denominator is missing or zero.
"""
from __future__ import annotations

from typing import Iterable

from app.schemas.analytics import Post
from app.schemas.campaigns import CampaignDaily

TYPE_LABELS = {
    "educational": "Educational", "promotional": "Promotional", "industry_news": "Industry news",
    "short_video": "Short video", "carousel": "Carousel", "testimonial": "Testimonial",
    "poll": "Question / poll",
}
PLATFORM_SHORT = {"Facebook": "FB", "Instagram": "IG", "LinkedIn": "LI", "TikTok": "TT"}
WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
WEEKDAYS_LONG = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
DAYPARTS = [("Early", 5, 9), ("Morning", 9, 12), ("Midday", 12, 15),
            ("Afternoon", 15, 18), ("Evening", 18, 21), ("Late", 21, 24)]


def safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator == 0:
        return None
    return numerator / denominator


def sum_optional(values: Iterable[float | int | None]) -> float | int | None:
    """Sum ignoring None. Returns None only if *every* value is None."""
    vals = [v for v in values if v is not None]
    return sum(vals) if vals else None


def pct_change(current: float | None, previous: float | None) -> float | None:
    """Relative change as a ratio (0.12 = +12%). None when undefined."""
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / previous


def daypart_index(hour: int) -> int | None:
    for i, (_, lo, hi) in enumerate(DAYPARTS):
        if lo <= hour < hi:
            return i
    return None


def daypart_label(i: int) -> str:
    name, lo, hi = DAYPARTS[i]
    return f"{name} ({lo:02d}:00-{hi % 24:02d}:00)"


def aggregate_posts(posts: list[Post]) -> dict:
    reach = sum(p.reach or 0 for p in posts)
    eng = sum(p.engagements or 0 for p in posts)
    return dict(
        posts=len(posts), reach=reach, impressions=sum(p.impressions or 0 for p in posts),
        likes=sum(p.likes or 0 for p in posts), comments=sum(p.comments or 0 for p in posts),
        shares=sum(p.shares or 0 for p in posts), saves=sum(p.saves or 0 for p in posts),
        link_clicks=sum(p.link_clicks or 0 for p in posts), engagements=eng,
        engagement_rate=safe_div(eng, reach),
    )


def aggregate_ads(rows: list[CampaignDaily]) -> dict:
    spend = round(sum(r.spend for r in rows), 2)
    clicks = sum(r.clicks for r in rows)
    imps = sum(r.impressions for r in rows)
    conversions = sum_optional(r.conversions for r in rows)
    revenue = sum_optional(r.revenue for r in rows)
    # CPA and ROAS only use spend from rows where the outcome is actually tracked.
    spend_conv = sum(r.spend for r in rows if r.conversions is not None)
    spend_rev = sum(r.spend for r in rows if r.revenue is not None)
    clicks_conv = sum(r.clicks for r in rows if r.conversions is not None)
    return dict(
        rows=len(rows), spend=spend, impressions=imps, reach=sum(r.reach for r in rows),
        clicks=clicks, conversions=conversions, revenue=revenue,
        ctr=safe_div(clicks, imps),
        cpc=safe_div(spend, clicks),
        cpa=safe_div(spend_conv, conversions) if conversions else None,
        conversion_rate=safe_div(conversions, clicks_conv) if conversions is not None else None,
        roas=safe_div(revenue, spend_rev),
    )


def combined_kpis(posts: list[Post], rows: list[CampaignDaily]) -> dict:
    """The eight headline KPIs, from organic posts + paid campaign rows."""
    o, a = aggregate_posts(posts), aggregate_ads(rows)
    return dict(
        reach=o["reach"] + a["reach"], impressions=o["impressions"] + a["impressions"],
        engagement_rate=o["engagement_rate"], link_clicks=o["link_clicks"] + a["clicks"],
        spend=a["spend"], conversions=a["conversions"], cpc=a["cpc"], roas=a["roas"],
        engagements=o["engagements"], organic=o, paid=a,
    )


# Text formatters (used in server-written insight sentences).
def fmt_compact(v: float) -> str:
    for div, suf in ((1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"{v / div:.1f}{suf}"
    return f"{v:.0f}"


def fmt_money(v: float, decimals: int = 2) -> str:
    return f"${v:,.{decimals}f}"


def fmt_kind(kind: str, v: float | None) -> str:
    """Format a KPI value by kind. None is shown as n/a (undefined or not tracked)."""
    if v is None:
        return "n/a"
    return {
        "compact": fmt_compact, "int": lambda x: f"{x:,.0f}", "percent": lambda x: f"{x:.1%}",
        "money0": lambda x: fmt_money(x, 0), "money2": fmt_money, "ratio": lambda x: f"{x:.2f}x",
    }[kind](v)


def group_stats(posts: list[Post], key) -> dict:
    """Per-group performance: post count, engagement rate and per-post averages."""
    groups: dict = {}
    for p in posts:
        groups.setdefault(key(p), []).append(p)
    out = {}
    for k, ps in groups.items():
        a = aggregate_posts(ps)
        n = a["posts"]
        out[k] = dict(n=n, er=a["engagement_rate"], avg_reach=a["reach"] / n, saves_pp=a["saves"] / n,
                      shares_pp=a["shares"] / n, clicks_pp=a["link_clicks"] / n, comments_pp=a["comments"] / n)
    return out
