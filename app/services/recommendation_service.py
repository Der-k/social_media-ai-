"""Content recommendations.

Pipeline (the order in the project brief):
  1. Retrieve published posts and campaign records.
  2. Calculate metrics in Python.
  3. Find high-performing and under-performing content.
  4. Compare by platform, format, topic and posting time.
  5. Summarise the findings as numbered CANDIDATES.
  6. Send the compact summary to Groq.
  7. The model chooses, prioritises and words 3-5 candidates (validated JSON).
  8. Python attaches the supporting data, confidence and posting window.
  9. The user may save a recommendation as a draft.

The model never sets a platform, format, confidence or statistic. Numbers in its prose are
checked against the candidate's evidence, and unverified prose is replaced by a template.
Without Groq, a rule-based mode produces the same structure from templates, clearly labelled.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from math import sqrt

from app.repositories import analytics_repository as repo
from app.repositories import campaign_repository, content_repository
from app.repositories import recommendation_repository as rec_repo
from app.schemas.analytics import PLATFORMS
from app.schemas.content import DraftInput
from app.schemas.recommendations import (
    SUCCESS_METRICS, GenerateRecommendationsRequest, LLMRecommendationSet, Recommendation,
    RecommendationBatch, SupportingStat,
)
from app.services import ai_service, content_service, metrics as m
from app.services.ai_service import AIUnavailable

MIN_HISTORY_POSTS = 20
MAX_RECS = 5
MIN_GROUP = 3            # fewer posts than this is an anecdote, not a pattern
LABEL = m.TYPE_LABELS


class RecommendationConflict(Exception):
    pass


class RecommendationNotFound(Exception):
    pass


# --------------------------------------------------------------------------- #
# Step 2-4: measure
# --------------------------------------------------------------------------- #
@dataclass
class Base:
    n: int
    er: float | None
    avg_reach: float
    saves_pp: float
    shares_pp: float
    clicks_pp: float


@dataclass
class Group:
    platform: str
    key: str
    posts: list
    n: int
    er: float | None
    er_lift: float | None
    reach_lift: float | None
    above: float          # share of posts at or above the platform's average engagement rate
    avg_reach: float
    saves_pp: float
    shares_pp: float
    clicks_pp: float
    share: float          # share of the platform's posts


@dataclass
class Candidate:
    id: str = ""
    kind: str = "publish_more"
    platform: str = ""
    format: str = ""
    focus: str = "engagement"
    topic_options: list[tuple[str, str]] = field(default_factory=list)
    stats: list[SupportingStat] = field(default_factory=list)
    evidence_n: int = 0
    confidence: str = "low"
    confidence_note: str = ""
    is_test: bool = False
    score: float = 0.0
    campaign_id: str | None = None
    window: str | None = None
    pipeline: str | None = None
    headline: str = ""
    template_reason: str = ""
    alt: str = ""         # for reduce: the format to publish instead

    def line(self) -> str:
        opts = "; ".join(t[1] for t in self.topic_options) or "none"
        ev = "; ".join(f"{s.label}: {s.value}" for s in self.stats)
        return (f"[{self.id}] kind={self.kind} | platform={self.platform} | format={LABEL[self.format]} | "
                f"test={'yes' if self.is_test else 'no'} | confidence={self.confidence} ({self.confidence_note}) | "
                f"topic options: {opts} | evidence: {ev} | window: {self.window or 'not enough data'}"
                + (f" | pipeline: {self.pipeline}" if self.pipeline else ""))


@dataclass
class Analysis:
    posts: list
    bases: dict[str, Base]
    candidates: list[Candidate]
    matrix: list[dict]
    pipeline: list[str]
    campaigns: int


def _bases(posts) -> dict[str, Base]:
    out = {}
    for pl in PLATFORMS:
        ps = [p for p in posts if p.platform == pl]
        if not ps:
            continue
        a, n = m.aggregate_posts(ps), len(ps)
        out[pl] = Base(n, a["engagement_rate"], a["reach"] / n, a["saves"] / n, a["shares"] / n, a["link_clicks"] / n)
    return out


def _groups(posts, keyfn, bases) -> dict:
    buckets: dict = {}
    for p in posts:
        buckets.setdefault((p.platform, keyfn(p)), []).append(p)
    out = {}
    for (pl, key), ps in buckets.items():
        b, n = bases[pl], len(ps)
        a = m.aggregate_posts(ps)
        er = a["engagement_rate"]
        out[(pl, key)] = Group(
            platform=pl, key=key, posts=ps, n=n, er=er, er_lift=m.safe_div(er, b.er),
            reach_lift=m.safe_div(a["reach"] / n, b.avg_reach),
            above=sum(1 for p in ps if p.engagement_rate is not None and b.er and p.engagement_rate >= b.er) / n,
            avg_reach=a["reach"] / n, saves_pp=a["saves"] / n, shares_pp=a["shares"] / n,
            clicks_pp=a["link_clicks"] / n, share=n / b.n)
    return out


def _confidence(n: int, strength: float, agree: float) -> str:
    """high / medium / low from sample size, size of the effect and how consistent it is."""
    if n >= 8 and strength >= 0.25 and agree >= 0.70:
        return "high"
    if n >= 5 and strength >= 0.12 and agree >= 0.60:
        return "medium"
    return "low"


def _topic_options(posts, platform, fmt, bases, limit=3) -> list[tuple[str, str]]:
    in_fmt = [p for p in posts if p.platform == platform and p.content_type == fmt]
    opts = [g for g in _groups(in_fmt, lambda p: p.topic, bases).values() if g.n >= 2]
    if len(opts) < 2:
        platform_posts = [p for p in posts if p.platform == platform]
        opts = [g for g in _groups(platform_posts, lambda p: p.topic, bases).values() if g.n >= MIN_GROUP]
    opts.sort(key=lambda g: -(g.er or 0))
    return [(g.key, f"{g.key} ({g.er:.1%} engagement, {g.n} posts)") for g in opts[:limit]]


def _window(posts, platform, fmt) -> str | None:
    def best(ps):
        parts = m.group_stats(ps, lambda p: m.daypart_index(p.published_at.hour))
        c = [(i, s) for i, s in parts.items() if i is not None and s["n"] >= MIN_GROUP]
        return max(c, key=lambda kv: kv[1]["er"]) if c else None
    on_platform = [p for p in posts if p.platform == platform]
    hit, scope = best([p for p in on_platform if p.content_type == fmt]), f"{LABEL[fmt]} on {platform}"
    if not hit:
        hit, scope = best(on_platform), f"all {platform} posts"
    if not hit:
        return None
    i, s = hit
    return f"{m.daypart_label(i)}: {s['er']:.1%} engagement across {s['n']} posts ({scope})"


def _stats(g: Group, b: Base) -> list[SupportingStat]:
    pl, fmt = g.platform, LABEL[g.key]
    return [
        SupportingStat(label=f"{pl} {fmt.lower()} engagement rate",
                       value=f"{g.er:.1%} vs {b.er:.1%} platform average ({g.er_lift - 1:+.0%})"),
        SupportingStat(label="Posts analysed", value=f"{g.n} ({g.above:.0%} at or above the platform average)"),
        SupportingStat(label="Average reach per post", value=f"{g.avg_reach:,.0f} vs {b.avg_reach:,.0f}"),
        SupportingStat(label="Saves / shares per post",
                       value=f"{g.saves_pp:.0f} / {g.shares_pp:.0f} vs {b.saves_pp:.0f} / {b.shares_pp:.0f}"),
    ]


def _few(n: int) -> str:
    return "no" if n == 0 else f"only {n}"


def _pipeline_note(pipeline_posts, platform, fmt, topics) -> str | None:
    for p in pipeline_posts:
        if p.platform == platform and p.content_type == fmt:
            same = " on the same topic" if p.topic in topics else ""
            return f"A {p.status} {LABEL[fmt].lower()} for {platform}{same} already exists: \"{content_service_snip(p.caption)}\""
    return None


def content_service_snip(text: str, n: int = 60) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1] + "..."


def build_analysis() -> Analysis:
    posts = repo.select_posts()                                   # step 1: all published history
    bases = _bases(posts)                                         # step 2
    combos = _groups(posts, lambda p: p.content_type, bases)      # step 4: platform x format
    topics = _groups(posts, lambda p: p.topic, bases)
    pipeline = [p for p in content_repository.list_posts() if p.status in ("draft", "proposed")]
    cands: list[Candidate] = []

    def best_format(platform, exclude=None):
        pool = [g for (pl, _), g in combos.items()
                if pl == platform and g.n >= 4 and g.key != exclude and (g.er_lift or 0) >= 1.0]
        return max(pool, key=lambda g: g.er_lift) if pool else None

    # --- publish more: formats that beat their platform's average (step 3, high performers) ---
    for g in combos.values():
        b = bases[g.platform]
        if g.n < 4 or g.er_lift is None:
            continue
        focus = "engagement" if g.er_lift >= 1.15 else "reach" if (g.reach_lift or 0) >= 1.30 else None
        if not focus or (focus == "engagement" and g.above < 0.6):
            continue
        strength = (g.er_lift if focus == "engagement" else g.reach_lift) - 1
        agree = g.above
        opts = _topic_options(posts, g.platform, g.key, bases)
        c = Candidate(kind="publish_more", platform=g.platform, format=g.key, focus=focus, topic_options=opts,
                      stats=_stats(g, b), evidence_n=g.n, confidence=_confidence(g.n, strength, agree),
                      confidence_note=f"{g.n} posts, {g.above:.0%} at or above the platform average",
                      score=strength * sqrt(g.n), window=_window(posts, g.platform, g.key))
        metric = (f"{g.er:.1%} engagement vs {b.er:.1%}" if focus == "engagement"
                  else f"{g.avg_reach:,.0f} average reach vs {b.avg_reach:,.0f}")
        c.headline = f"{g.platform} {LABEL[g.key].lower()}: {metric}"
        c.template_reason = (
            f"{g.platform} {LABEL[g.key].lower()} posts earn {g.er:.1%} engagement against {b.er:.1%} for {g.platform} overall "
            f"({g.er_lift - 1:+.0%}) across {g.n} posts, and {g.above:.0%} of them are at or above the platform average."
            if focus == "engagement" else
            f"{g.platform} {LABEL[g.key].lower()} posts reach {g.avg_reach:,.0f} people on average against {b.avg_reach:,.0f} "
            f"for {g.platform} overall, across {g.n} posts.")
        cands.append(c)

    # --- reduce: frequent formats that lag their platform (step 3, under-performers) ---
    for g in combos.values():
        b = bases[g.platform]
        if g.n < 5 or g.share < 0.20 or g.er_lift is None or g.er_lift > 0.80 or (1 - g.above) < 0.60:
            continue
        alt = best_format(g.platform, exclude=g.key)
        if not alt:
            continue
        opts = _topic_options(posts, g.platform, alt.key, bases)
        c = Candidate(kind="reduce", platform=g.platform, format=alt.key, topic_options=opts,
                      stats=[SupportingStat(label=f"{g.platform} {LABEL[g.key].lower()} engagement rate",
                                            value=f"{g.er:.1%} vs {b.er:.1%} platform average ({g.er_lift - 1:+.0%})"),
                             SupportingStat(label=f"Share of {g.platform} posts", value=f"{g.share:.0%} ({g.n} of {b.n} posts)"),
                             SupportingStat(label=f"Better option: {LABEL[alt.key].lower()}",
                                            value=f"{alt.er:.1%} engagement across {alt.n} posts")],
                      evidence_n=g.n, confidence=_confidence(g.n, 1 - g.er_lift, 1 - g.above),
                      confidence_note=f"{g.n} posts, {1 - g.above:.0%} below the platform average",
                      score=(1 - g.er_lift) * sqrt(g.n), window=_window(posts, g.platform, alt.key), alt=alt.key)
        c.headline = f"{g.platform}: publish fewer {LABEL[g.key].lower()} posts, more {LABEL[alt.key].lower()}"
        c.template_reason = (
            f"{LABEL[g.key]} posts are {g.share:.0%} of {g.platform} output but earn {g.er:.1%} engagement against {b.er:.1%} "
            f"for the platform. {LABEL[alt.key]} earns {alt.er:.1%} across {alt.n} posts, so those slots may work harder.")
        cands.append(c)

    # --- repurpose: strong topic on one platform, thin on another (step 4 across platforms) ---
    seen_topics: set[str] = set()
    for (pl, topic), g in sorted(topics.items(), key=lambda kv: -((kv[1].er_lift or 0) * sqrt(kv[1].n))):
        if g.n < MIN_GROUP or (g.er_lift or 0) < 1.15 or topic in seen_topics:
            continue
        targets = []
        for target in PLATFORMS:
            if target == pl or target not in bases:
                continue
            have = topics.get((target, topic))
            fmt_g = best_format(target)
            if (have.n if have else 0) < MIN_GROUP and fmt_g:
                targets.append((target, have.n if have else 0, fmt_g))
        if not targets:
            continue
        dominant = max({p.content_type for p in g.posts}, key=lambda t: sum(p.content_type == t for p in g.posts))
        target, have_n, fmt_g = max(targets, key=lambda t: (t[2].key != dominant, t[2].er_lift))
        b = bases[pl]
        c = Candidate(kind="repurpose", platform=target, format=fmt_g.key, is_test=True, confidence="low",
                      topic_options=[(topic, f"{topic} ({g.er:.1%} engagement on {pl}, {g.n} posts)")],
                      stats=[SupportingStat(label=f"'{topic}' on {pl}", value=f"{g.er:.1%} vs {b.er:.1%} platform average ({g.er_lift - 1:+.0%}), {g.n} posts"),
                             SupportingStat(label=f"'{topic}' on {target}", value=f"{have_n} posts so far"),
                             SupportingStat(label=f"{target} {LABEL[fmt_g.key].lower()} engagement rate", value=f"{fmt_g.er:.1%} across {fmt_g.n} posts")],
                      evidence_n=g.n, confidence_note=f"strong on {pl} ({g.n} posts) but {_few(have_n)} on {target}, so this is a test",
                      score=(g.er_lift - 1) * sqrt(g.n) * 0.7, window=_window(posts, target, fmt_g.key))
        c.headline = f"Repurpose '{topic}' from {pl} to {target} as a {LABEL[fmt_g.key].lower()}"
        c.template_reason = (
            f"'{topic}' earns {g.er:.1%} engagement on {pl} against {b.er:.1%} for the platform ({g.n} posts), but {target} has "
            f"{_few(have_n)} posts on it. {LABEL[fmt_g.key]} is the strongest {target} format in the data ({fmt_g.er:.1%}, {fmt_g.n} posts). "
            f"This is a test, not a proven pattern.")
        cands.append(c)
        seen_topics.add(topic)

    # --- test: a format that works elsewhere but is missing or thin here ---
    by_format: dict[str, list[Group]] = {}
    for g in combos.values():
        by_format.setdefault(g.key, []).append(g)
    tests = []
    for fmt, gs in by_format.items():
        strong = [g for g in gs if g.n >= 4 and (g.er_lift or 0) >= 1.15]
        if not strong:
            continue
        src = max(strong, key=lambda g: g.er_lift)
        for target in PLATFORMS:
            if target == src.platform or target not in bases or bases[target].n < 10:
                continue
            # A platform that is >= 80% one other format (e.g. TikTok video) is specialised: skip the test.
            top = max((g for (pl, _), g in combos.items() if pl == target), key=lambda g: g.share)
            if top.key != fmt and top.share >= 0.80:
                continue
            have = combos.get((target, fmt))
            if (have.n if have else 0) < MIN_GROUP:
                tests.append((src, target, have.n if have else 0))
    for src, target, have_n in sorted(tests, key=lambda t: -(t[0].er_lift or 0))[:2]:
        b = bases[src.platform]
        opts = _topic_options(posts, target, src.key, bases) or _topic_options(posts, src.platform, src.key, bases)
        c = Candidate(kind="test", platform=target, format=src.key, is_test=True, confidence="low", topic_options=opts,
                      stats=[SupportingStat(label=f"{src.platform} {LABEL[src.key].lower()} engagement rate", value=f"{src.er:.1%} vs {b.er:.1%} platform average ({src.er_lift - 1:+.0%}), {src.n} posts"),
                             SupportingStat(label=f"{target} {LABEL[src.key].lower()} posts so far", value=str(have_n))],
                      evidence_n=src.n, confidence_note=f"{_few(have_n)} {LABEL[src.key].lower()} posts on {target}, so there is no evidence either way",
                      score=(src.er_lift - 1) * 0.5, window=_window(posts, target, src.key))
        c.headline = f"Test {LABEL[src.key].lower()} on {target}"
        c.template_reason = (f"{LABEL[src.key]} earns {src.er:.1%} engagement on {src.platform} ({src.n} posts), but {target} has "
                             f"{_few(have_n)} such posts, so there is no evidence yet either way. A small test would show whether it carries over.")
        cands.append(c)

    # --- campaigns: link paid results to organic content (advisory only) ---
    end = repo.as_of()
    scored = []
    for camp in campaign_repository.list_campaigns():
        if camp.status != "active" or not camp.tracks_conversions:
            continue
        a = m.aggregate_ads(repo.select_ad_rows(campaign=camp.id))
        if a["spend"] >= 500 and a["roas"] is not None and camp.platform in bases:
            scored.append((camp, a))
    for camp, a in sorted(scored, key=lambda t: -t[1]["roas"])[:1]:
        alt = best_format(camp.platform)
        if alt and a["roas"] >= 2.0:
            opts = _topic_options(posts, camp.platform, alt.key, bases)
            conv = a["conversions"] or 0
            conf = "high" if conv >= 50 and a["spend"] >= 2000 else "medium" if conv >= 20 else "low"
            c = Candidate(kind="support_campaign", platform=camp.platform, format=alt.key, topic_options=opts, campaign_id=camp.id,
                          stats=[SupportingStat(label=f"{camp.name} ROAS", value=f"{a['roas']:.2f}x on {m.fmt_money(a['spend'], 0)} spend"),
                                 SupportingStat(label="Conversions", value=f"{conv:,.0f} at {m.fmt_money(a['cpa'], 0)} each"),
                                 SupportingStat(label=f"Strongest organic {camp.platform} format", value=f"{LABEL[alt.key].lower()}, {alt.er:.1%} engagement across {alt.n} posts")],
                          evidence_n=conv, confidence=conf, confidence_note=f"{conv:,.0f} conversions on {m.fmt_money(a['spend'], 0)} spend",
                          score=min(a["roas"], 6) / 4, window=_window(posts, camp.platform, alt.key))
            c.headline = f"Support '{camp.name}' with organic {LABEL[alt.key].lower()}"
            c.template_reason = (f"'{camp.name}' returns {a['roas']:.2f}x ROAS ({conv:,.0f} conversions). Organic {LABEL[alt.key].lower()} is the strongest "
                                 f"organic format on {camp.platform} ({alt.er:.1%}), so it is a natural fit to build awareness around the same audience. "
                                 f"Any budget decision stays with a person.")
            cands.append(c)
    for camp, a in sorted(scored, key=lambda t: t[1]["roas"])[:1]:
        alt = best_format(camp.platform)
        if alt and a["roas"] < 1.5:
            opts = _topic_options(posts, camp.platform, alt.key, bases)
            c = Candidate(kind="test", platform=camp.platform, format=alt.key, topic_options=opts, campaign_id=camp.id, is_test=True,
                          stats=[SupportingStat(label=f"{camp.name} ROAS", value=f"{a['roas']:.2f}x on {m.fmt_money(a['spend'], 0)} spend"),
                                 SupportingStat(label="Cost per click", value=m.fmt_money(a["cpc"])),
                                 SupportingStat(label=f"Strongest organic {camp.platform} format", value=f"{LABEL[alt.key].lower()}, {alt.er:.1%} engagement across {alt.n} posts")],
                          evidence_n=a["conversions"] or 0, confidence="low",
                          confidence_note="paid results are weak and the cause is not visible in this data, so treat any change as a test",
                          score=(1.5 - a["roas"]), window=_window(posts, camp.platform, alt.key))
            c.headline = f"Test a stronger organic angle alongside '{camp.name}'"
            c.template_reason = (f"'{camp.name}' returns {a['roas']:.2f}x ROAS at {m.fmt_money(a['cpc'])} per click. The data does not show why. "
                                 f"Testing the organic format that works best on {camp.platform} ({LABEL[alt.key].lower()}, {alt.er:.1%}) is a low-risk way "
                                 f"to learn what resonates. Whether to change spend is a human decision.")
            cands.append(c)

    # --- finish: pipeline notes, drop empties, order, number ---
    final = []
    for c in cands:
        if not c.topic_options:
            continue
        c.pipeline = _pipeline_note(pipeline, c.platform, c.format, {t[0] for t in c.topic_options})
        final.append(c)
    per_kind = {"publish_more": 4, "reduce": 2, "repurpose": 2, "test": 3, "support_campaign": 1}
    taken: dict[str, int] = {}
    chosen = []
    for c in sorted(final, key=lambda c: -c.score):
        if taken.get(c.kind, 0) < per_kind[c.kind]:
            chosen.append(c)
            taken[c.kind] = taken.get(c.kind, 0) + 1
    for i, c in enumerate(chosen, 1):
        c.id = f"c{i}"

    matrix = []
    for fmt, label in LABEL.items():
        row = dict(format=fmt, label=label, cells=[])
        for pl in PLATFORMS:
            g = combos.get((pl, fmt))
            row["cells"].append(dict(platform=pl, n=g.n if g else 0, er=g.er if g else None, lift=g.er_lift if g else None))
        matrix.append(row)
    return Analysis(posts, bases, chosen, matrix, [f"{p.status}: {p.platform} {LABEL[p.content_type]} on '{p.topic}'" for p in pipeline],
                    len(campaign_repository.list_campaigns()))


# --------------------------------------------------------------------------- #
# Wording defaults (used by rule-based mode and as the fallback for unverified AI text)
# --------------------------------------------------------------------------- #
BRIEFS = {
    "carousel": "A 5-slide carousel on {t}: the problem, three practical steps, and one takeaway to save.",
    "short_video": "A 30-45 second video on {t}: a hook in the first 3 seconds, one practical tip, and on-screen text for the takeaway.",
    "educational": "A short how-to post on {t} with one practical tip readers can use today.",
    "testimonial": "A customer story on {t}: the situation before, what changed, and the result. Add real details: [customer name], [result].",
    "poll": "A one-question poll on {t} with 3-4 answer options, inviting readers to explain their choice in the comments.",
    "industry_news": "A short take on a recent industry development related to {t}, with one clear opinion.",
    "promotional": "A product update on {t} with one clear benefit and a single offer.",
}
CTAS = {"carousel": "Save this for your next planning session.", "short_video": "Follow for one practical tip a week.",
        "educational": "Try this today and tell us how it goes.", "testimonial": "Read the full story.",
        "poll": "Vote and tell us why in the comments.", "industry_news": "Share your view in the comments.",
        "promotional": "See what is new."}
METRICS = {"carousel": "Saves per post", "short_video": "Reach", "educational": "Shares per post",
           "testimonial": "Link clicks", "poll": "Comments", "industry_news": "Engagement rate", "promotional": "Link clicks"}
_NUM = re.compile(r"\d[\d,]*\.?\d*%?")


def _unverified(text: str, allowed_text: str) -> list[str]:
    """Numbers in `text` that do not appear in the evidence. Small counts (12 or fewer) are allowed."""
    norm = lambda s: s.rstrip(".,").replace(",", "")  # noqa: E731
    allowed = {norm(t) for t in _NUM.findall(allowed_text)}
    bad = []
    for tok in _NUM.findall(text):
        n = norm(tok)
        try:
            val = float(n.rstrip("%"))
        except ValueError:
            continue
        if not n.endswith("%") and val <= 12:
            continue
        if n not in allowed:
            bad.append(tok)
    return bad


def _summary_template(an: Analysis) -> str:
    ups = [c for c in an.candidates if c.kind == "publish_more"]
    downs = [c for c in an.candidates if c.kind == "reduce"]
    parts = [f"Across {len(an.posts)} published posts, the clearest strength is {ups[0].headline}." if ups
             else f"Across {len(an.posts)} published posts, no format clearly beats its platform average yet."]
    if downs:
        parts.append(f"The clearest weakness: {downs[0].headline}.")
    tests = sum(c.is_test for c in an.candidates)
    if tests:
        parts.append(f"{tests} suggestion{'s are' if tests != 1 else ' is'} tests because the history is thin.")
    return " ".join(parts)


def _build_rec(c: Candidate, rank: int, batch_id: str, now: datetime, source: str, *, topic=None, brief=None,
               reason=None, cta=None, metric=None) -> Recommendation:
    topics = [t[0] for t in c.topic_options]
    topic = topic if topic in topics else topics[0]
    default_metric = "Reach" if c.focus == "reach" else METRICS[c.format]
    return Recommendation(
        id=f"{batch_id}_r{rank}", batch_id=batch_id, priority=rank, kind=c.kind, topic=topic, format=c.format,
        platform=c.platform, caption_brief=brief or BRIEFS[c.format].format(t=topic.lower()),
        reason=reason or c.template_reason, reason_source="ai" if reason else "template",
        supporting_data=c.stats, posting_window=c.window, confidence=c.confidence, confidence_note=c.confidence_note,
        evidence_n=c.evidence_n, call_to_action=cta or CTAS[c.format],
        success_metric=metric if metric in SUCCESS_METRICS else default_metric, focus=c.focus,
        is_test=c.is_test, campaign_id=c.campaign_id, in_pipeline=c.pipeline, source=source, created_at=now)


# --------------------------------------------------------------------------- #
# Steps 5-8: generate
# --------------------------------------------------------------------------- #
def _prompt(an: Analysis) -> str:
    lines = [f"DATA AS OF {repo.as_of().isoformat()} (fictional demo data). {len(an.posts)} published posts over "
             f"{repo.get_meta()['history_days']} days, {an.campaigns} ad campaigns.", "", "PLATFORM AVERAGES (organic):"]
    for pl, b in an.bases.items():
        lines.append(f"- {pl}: engagement rate {b.er:.1%}, average reach {b.avg_reach:,.0f}, {b.n} posts")
    lines += ["", "EXISTING PIPELINE (already drafted or planned; avoid duplicating):"]
    lines += [f"- {p}" for p in an.pipeline] or ["- none"]
    lines += ["", "CANDIDATES (choose only from these):"] + [c.line() for c in an.candidates]
    lines += ["", "ALLOWED SUCCESS METRICS: " + ", ".join(SUCCESS_METRICS), "",
              "Choose 3 to 5 candidates and return the JSON object described in the instructions."]
    return "\n".join(lines)


def _fingerprint(prompt: str, mode: str) -> str:
    return ai_service.make_cache_key("recs", mode, prompt)


def _pick_rules(an: Analysis) -> list[Candidate]:
    taken: dict[str, int] = {}
    out = []
    rank = {"high": 2, "medium": 1, "low": 0}
    for c in sorted(an.candidates, key=lambda c: (-rank[c.confidence], -c.score)):
        if taken.get(c.kind, 0) < 2 and len(out) < MAX_RECS:
            out.append(c)
            taken[c.kind] = taken.get(c.kind, 0) + 1
    return out


async def generate(req: GenerateRecommendationsRequest) -> dict:
    an = build_analysis()
    if len(an.posts) < MIN_HISTORY_POSTS or not an.candidates:
        return dict(status="insufficient", message=(
            f"There are only {len(an.posts)} published posts and no clear patterns yet. At least {MIN_HISTORY_POSTS} posts "
            "are needed before recommendations mean anything. Publish more, or run a few tests, then try again."))

    prompt = _prompt(an)
    fp = _fingerprint(prompt, req.mode)
    batches = rec_repo.list_batches()
    last = next((b for b in reversed(batches) if b.source == req.mode), None)
    if last and last.fingerprint == fp and not req.fresh:
        return dict(status="unchanged", batch_id=last.id, created_at=last.created_at.isoformat(),
                    message="The data has not changed since the last analysis, so no new request was made.")

    now = datetime.combine(repo.as_of(), datetime.now().time()).replace(microsecond=0)
    batch_id = f"batch_{rec_repo.next_batch_number():03d}"
    by_id = {c.id: c for c in an.candidates}
    recs: list[Recommendation] = []
    model, summary, summary_source, cached = None, _summary_template(an), "template", False

    if req.mode == "rules":
        for rank, c in enumerate(_pick_rules(an), 1):
            recs.append(_build_rec(c, rank, batch_id, now, "rules"))
    else:
        messages = [{"role": "system", "content": ai_service.RECOMMENDER_SYSTEM}, {"role": "user", "content": prompt}]
        res = await ai_service.generate_structured(
            messages, LLMRecommendationSet, cache_key=ai_service.make_cache_key("recs-llm", messages),
            fresh=req.fresh, max_tokens=3000, temperature=0.4)
        out: LLMRecommendationSet = res["object"]
        model, cached = res["model"], res["cached"]
        used: set[str] = set()
        for item in out.recommendations:
            c = by_id.get(item.candidate_id.strip().strip("[]").lower())
            if c is None or c.id in used or len(recs) >= MAX_RECS:
                continue                       # unknown, duplicate, or beyond the limit
            used.add(c.id)
            evidence = c.line()
            # Numbers in the model's prose must come from the evidence; otherwise use the template text.
            reason = item.reason if not _unverified(item.reason, evidence) else None
            brief = item.caption_brief if not _unverified(item.caption_brief, evidence) else None
            cta = item.call_to_action if not _unverified(item.call_to_action, evidence) else None
            recs.append(_build_rec(c, len(recs) + 1, batch_id, now, "ai", topic=item.topic, brief=brief,
                                   reason=reason, cta=cta, metric=item.success_metric))
        if not recs:
            raise AIUnavailable("bad_response", "The AI did not choose any valid recommendation, so nothing was saved. Try again.", 502)
        if not _unverified(out.overall_summary, prompt):
            summary, summary_source = out.overall_summary, "ai"

    batch = RecommendationBatch(id=batch_id, created_at=now, source=req.mode, model=model, fingerprint=fp,
                                posts_analysed=len(an.posts), candidate_count=len(an.candidates),
                                summary=summary, summary_source=summary_source)
    rec_repo.add_batch(batch, recs)
    return dict(status="created", batch_id=batch_id, count=len(recs), source=req.mode, model=model, cached=cached)


# --------------------------------------------------------------------------- #
# Page data, save, dismiss
# --------------------------------------------------------------------------- #
KIND_META = {
    "publish_more": ("Publish more", "good"), "test": ("Run a test", "violet"), "reduce": ("Publish less", "warn"),
    "repurpose": ("Repurpose", "blue"), "support_campaign": ("Support a campaign", "blue"),
}


def _view(r: Recommendation) -> dict:
    d = r.model_dump()
    d["type_label"] = LABEL[r.format]
    d["kind_label"], d["kind_tone"] = KIND_META.get(r.kind, KIND_META["publish_more"])
    d["created_label"] = f"{r.created_at:%b %d, %H:%M}".replace(" 0", " ")
    return d


def page_data(platform: str = "all") -> dict:
    an = build_analysis()
    batches = rec_repo.list_batches()
    all_recs = rec_repo.list_recommendations()
    latest = batches[-1] if batches else None
    current = [r for r in all_recs if latest and r.batch_id == latest.id and r.status != "dismissed"]
    shown = [r for r in current if platform == "all" or r.platform == platform]
    history = [r for r in all_recs if not (latest and r.batch_id == latest.id) or r.status == "dismissed"]
    history.sort(key=lambda r: (r.created_at, -r.priority), reverse=True)
    return dict(
        batch=latest.model_dump(mode="json") if latest else None,
        batch_label=(f"{latest.created_at:%b %d, %H:%M}".replace(" 0", " ") if latest else None),
        recs=[_view(r) for r in sorted(shown, key=lambda r: r.priority)], hidden_by_filter=len(current) - len(shown),
        history=[_view(r) for r in history],
        matrix=an.matrix, candidates=[dict(id=c.id, kind=KIND_META[c.kind][0], headline=c.headline, confidence=c.confidence,
                                           is_test=c.is_test, note=c.confidence_note) for c in an.candidates],
        posts_analysed=len(an.posts), campaigns=an.campaigns, enough=len(an.posts) >= MIN_HISTORY_POSTS,
        base={pl: dict(er=b.er, n=b.n) for pl, b in an.bases.items()},
    )


def save_as_draft(rec_id: str):
    r = rec_repo.get_recommendation(rec_id)
    if r is None:
        raise RecommendationNotFound(rec_id)
    if r.status == "saved" and r.saved_post_id:
        raise RecommendationConflict(r.saved_post_id)
    camp = campaign_repository.get_campaign(r.campaign_id) if r.campaign_id else None
    caption = f"{r.caption_brief}\n\nCall to action: {r.call_to_action}"[:3000]
    post = content_service.create_draft(
        DraftInput(platform=r.platform, content_type=r.format, topic=r.topic, caption=caption, status="draft",
                   campaign_id=camp.id if camp and camp.platform == r.platform else None),
        source={"ai": "ai", "rules": "rules"}.get(r.source, "sample"))
    rec_repo.update_recommendation(rec_id, status="saved", saved_post_id=post.id)
    return post


def set_status(rec_id: str, status: str) -> None:
    r = rec_repo.get_recommendation(rec_id)
    if r is None:
        raise RecommendationNotFound(rec_id)
    if r.status == "saved":
        raise RecommendationConflict(r.saved_post_id or "")
    rec_repo.update_recommendation(rec_id, status=status)
