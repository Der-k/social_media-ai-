"""Deterministic fictional demo data for "Brightloom", a made-up workflow app.

Everything here is invented. The generator embeds believable patterns
(carousels earn saves, promotional posts lag, evening video reaches further,
LinkedIn likes weekday mornings) so the analytics have something real to find.
Calling build_seed() twice with the same anchor date yields identical data.
"""
from __future__ import annotations

import copy
import random
import threading
from datetime import date, datetime, time, timedelta

SEED_VERSION = 1
HISTORY_DAYS = 90

# --------------------------------------------------------------------------- #
# Posting behaviour
# --------------------------------------------------------------------------- #
PLATFORM = {
    "Facebook":  dict(reach=3200, er=0.034, p=0.28, weekend_p=0.20, best=(12, 14)),
    "Instagram": dict(reach=5200, er=0.058, p=0.38, weekend_p=0.34, best=(18, 21)),
    "LinkedIn":  dict(reach=4300, er=0.046, p=0.58, weekend_p=0.0,  best=(8, 10)),
    "TikTok":    dict(reach=9500, er=0.070, p=0.22, weekend_p=0.26, best=(19, 22)),
}

TYPE_WEIGHTS = {
    "LinkedIn":  {"educational": .20, "carousel": .22, "industry_news": .20,
                  "testimonial": .15, "promotional": .13, "poll": .10},
    "Instagram": {"carousel": .30, "short_video": .28, "educational": .10,
                  "testimonial": .10, "promotional": .15, "poll": .07},
    "Facebook":  {"promotional": .32, "educational": .14, "testimonial": .14,
                  "poll": .14, "industry_news": .10, "carousel": .06, "short_video": .10},
    "TikTok":    {"short_video": .85, "educational": .10, "poll": .05},
}

TYPE_TOPICS = {
    "educational":   ["Focus time", "Weekly planning", "Time management", "Remote team habits", "Workflow templates"],
    "carousel":      ["Workflow templates", "Weekly planning", "Time management", "Focus time", "Remote team habits"],
    "short_video":   ["Remote team habits", "Time management", "Focus time", "Product updates"],
    "promotional":   ["Product updates", "Workflow templates", "Customer onboarding"],
    "industry_news": ["Industry trends", "Remote team habits"],
    "testimonial":   ["Customer onboarding", "Workflow templates"],
    "poll":          ["Remote team habits", "Weekly planning", "Industry trends", "Focus time"],
}

TOPIC_R = {"Workflow templates": 1.22, "Focus time": 1.15, "Weekly planning": 1.05,
           "Remote team habits": 1.0, "Time management": 0.98, "Customer onboarding": 1.05,
           "Industry trends": 0.92, "Product updates": 0.80}

TYPE_REACH = {"short_video": 1.6, "carousel": 1.1, "educational": 1.0, "testimonial": 0.95,
              "industry_news": 0.9, "poll": 0.85, "promotional": 0.7}
TYPE_ENG = {"carousel": 1.35, "educational": 1.15, "testimonial": 1.2, "short_video": 1.1,
            "poll": 1.0, "industry_news": 0.95, "promotional": 0.6}
PLATFORM_TYPE_ENG = {("LinkedIn", "testimonial"): 1.3, ("LinkedIn", "industry_news"): 1.15,
                     ("Instagram", "carousel"): 1.15, ("Facebook", "promotional"): 0.85}
# likes, comments, shares, saves
SPLIT = {"carousel": (.48, .07, .15, .30), "educational": (.52, .08, .16, .24),
         "industry_news": (.58, .12, .22, .08), "short_video": (.56, .08, .24, .12),
         "testimonial": (.62, .12, .14, .12), "poll": (.45, .35, .08, .12),
         "promotional": (.72, .06, .06, .16)}
LINK_CTR = {"promotional": .022, "educational": .012, "carousel": .011, "testimonial": .016,
            "industry_news": .018, "short_video": .006, "poll": .003}

CAPTIONS = {
    "educational": [
        "Our short guide to {t}: what to start, what to stop, and what to measure.",
        "Most teams lose hours every week without a clear approach to {t}. Here is a simple routine.",
        "Three small changes that make {t} easier for busy teams.",
    ],
    "carousel": [
        "Swipe through: 5 steps to better {t}. Save this for your next team meeting.",
        "The {t} checklist, slide by slide. Which step is your team skipping?",
        "Before and after: how one team improved {t} in two weeks.",
    ],
    "short_video": [
        "60 seconds on {t}: one habit, big payoff.",
        "Watch how we handle {t} on a real Monday morning.",
        "POV: your team finally gets {t} under control.",
    ],
    "promotional": [
        "New this month: smarter tools for {t}. Start your free trial today.",
        "Spring offer: 20% off annual plans. See what is new in {t}.",
        "See how Brightloom helps with {t}. Book a 15-minute demo.",
    ],
    "industry_news": [
        "New survey: how small teams are changing their approach to {t}. Our take.",
        "What this week's headlines mean for {t}.",
        "Trend watch: {t} is reshaping how small teams plan their work.",
    ],
    "testimonial": [
        "\"Brightloom cut our planning time in half.\" A customer story about {t}.",
        "How a 12-person agency improved {t} with Brightloom.",
        "Customer spotlight: from scattered spreadsheets to a calm routine for {t}.",
    ],
    "poll": [
        "Quick poll: how does your team handle {t}? Tell us in the comments.",
        "Which part of {t} is your biggest challenge right now?",
        "Be honest: does your team have a clear process for {t}?",
    ],
}

# --------------------------------------------------------------------------- #
# Campaigns
# --------------------------------------------------------------------------- #
CAMPAIGNS = [
    dict(id="cmp_webinar", name="Spring Webinar Lead Gen", platform="LinkedIn",
         objective="Lead generation", status="active", start_ago=70, end_ago=None, planned=75,
         daily=88, cpm=26.0, ctr=.0092, cvr=.058, value=150, freq=1.35,
         drift=dict(ctr=.12, cvr=.10, cpm=0.0), shock=None, tracked=True,
         link_types=("educational", "testimonial", "carousel"),
         audience="Operations managers at companies with 10-200 employees"),
    dict(id="cmp_retarget", name="Product Demo Retargeting", platform="Facebook",
         objective="Conversions", status="active", start_ago=48, end_ago=None, planned=70,
         daily=62, cpm=11.5, ctr=.0125, cvr=.05, value=70, freq=2.1,
         drift=dict(ctr=.05, cvr=.15, cpm=-.05), shock=dict(days=7, cvr=1.28), tracked=True,
         link_types=("promotional", "testimonial"),
         audience="Website visitors from the last 30 days"),
    dict(id="cmp_tt_awareness", name="Short Video Awareness Push", platform="TikTok",
         objective="Awareness", status="active", start_ago=35, end_ago=None, planned=60,
         daily=55, cpm=5.8, ctr=.0048, cvr=0, value=0, freq=1.6,
         drift=dict(ctr=.0, cvr=0, cpm=-.08), shock=None, tracked=False,
         link_types=("short_video",), audience="Team leads and freelancers, ages 25-44"),
    dict(id="cmp_ig_traffic", name="Carousel Traffic Boost", platform="Instagram",
         objective="Traffic", status="active", start_ago=52, end_ago=None, planned=75,
         daily=48, cpm=9.2, ctr=.0165, cvr=.011, value=80, freq=1.5,
         drift=dict(ctr=-.05, cvr=-.25, cpm=.05), shock=dict(days=10, cpm=1.25, ctr=.88), tracked=True,
         link_types=("carousel",), audience="Small business owners, lookalike of newsletter subscribers"),
    dict(id="cmp_flash", name="Winter Flash Sale", platform="Facebook",
         objective="Sales", status="completed", start_ago=88, end_ago=60, planned=29,
         daily=70, cpm=12.0, ctr=.011, cvr=.045, value=70, freq=1.9,
         drift=dict(ctr=-.06, cvr=-.05, cpm=.04), shock=None, tracked=True,
         link_types=("promotional",), audience="Existing customers and warm audiences"),
    dict(id="cmp_influencer", name="Influencer Story Test", platform="Instagram",
         objective="Conversions", status="paused", start_ago=40, end_ago=14, planned=45,
         daily=40, cpm=14.0, ctr=.0062, cvr=.0075, value=160, freq=1.4,
         drift=dict(ctr=-.10, cvr=-.10, cpm=.12), shock=None, tracked=True,
         link_types=("short_video", "promotional"), audience="Followers of three micro-influencers"),
]

DRAFTS = [
    ("LinkedIn", "educational", "Focus time", "Draft: how we protect two hours of focus time every day. Add the team calendar screenshot.", "manual", None),
    ("Instagram", "carousel", "Workflow templates", "Draft carousel: 6 workflow templates we reuse every week. Needs final slide design.", "manual", None),
    ("TikTok", "short_video", "Remote team habits", "Draft script: the 30-second Friday wrap-up that keeps remote teams in sync.", "ai", None),
    ("Facebook", "poll", "Weekly planning", "Draft poll: do you plan your week on Sunday night or Monday morning?", "manual", 3),
    ("LinkedIn", "testimonial", "Customer onboarding", "Draft case study: how a 20-person studio onboarded in one afternoon.", "manual", 5),
]
PROPOSED = [
    ("Instagram", "carousel", "Time management", "Proposed: Time management in 5 slides. Save for your Monday planning session.", "ai", 2, 18),
    ("LinkedIn", "educational", "Weekly planning", "Proposed: a simple weekly planning routine for small teams, with one template to download.", "ai", 4, 9),
    ("TikTok", "short_video", "Focus time", "Proposed: 45 seconds on protecting focus time when everyone is in meetings.", "ai", 6, 20),
    ("Facebook", "testimonial", "Customer onboarding", "Proposed: customer story about moving from spreadsheets to a shared plan.", "manual", 8, 12),
]


# --------------------------------------------------------------------------- #
def _weighted(rng: random.Random, weights: dict[str, float]) -> str:
    return rng.choices(list(weights), weights=list(weights.values()))[0]


def _time_mult(platform: str, hour: int) -> float:
    lo, hi = PLATFORM[platform]["best"]
    if lo <= hour < hi:
        return 1.22
    if lo - 2 <= hour < hi + 2:
        return 1.0
    return 0.85


def _pick_hour(rng: random.Random, platform: str) -> int:
    lo, hi = PLATFORM[platform]["best"]
    if rng.random() < 0.55:
        return rng.randint(lo, hi - 1)
    return rng.randint(7, 22)


def _make_post_metrics(rng, platform, ctype, topic, hour, d, anchor):
    p = PLATFORM[platform]
    trend = 1 + 0.18 * ((d - (anchor - timedelta(days=HISTORY_DAYS))).days / HISTORY_DAYS)
    tm = _time_mult(platform, hour)
    wd_bonus = 1.1 if (platform == "LinkedIn" and d.weekday() in (1, 2, 3)) else 1.0
    reach = p["reach"] * trend * TYPE_REACH[ctype] * TOPIC_R[topic] * tm * wd_bonus * rng.lognormvariate(0, .22)
    er = (p["er"] * TYPE_ENG[ctype] * PLATFORM_TYPE_ENG.get((platform, ctype), 1.0)
          * TOPIC_R[topic] ** .5 * tm * rng.lognormvariate(0, .15))
    er = min(er, .22)
    reach = int(reach)
    eng = reach * er
    sl, sc, ss, sv = SPLIT[ctype]
    jitter = lambda: rng.uniform(.9, 1.1)  # noqa: E731
    likes, comments, shares, saves = (int(eng * s * jitter()) for s in (sl, sc, ss, sv))
    return dict(
        reach=reach,
        impressions=int(reach * rng.uniform(1.15, 1.55)),
        likes=likes, comments=comments, shares=shares, saves=saves,
        link_clicks=int(reach * LINK_CTR[ctype] * rng.uniform(.7, 1.3)),
    )


def _stochastic_round(rng: random.Random, x: float) -> int:
    base = int(x)
    return base + (1 if rng.random() < x - base else 0)


def _build_campaigns(rng: random.Random, anchor: date):
    campaigns, daily = [], []
    for c in CAMPAIGNS:
        start = anchor - timedelta(days=c["start_ago"])
        last = anchor - timedelta(days=c["end_ago"] or 0)
        campaigns.append(dict(
            id=c["id"], name=c["name"], platform=c["platform"], objective=c["objective"],
            status=c["status"], budget=float(round(c["daily"] * c["planned"], -1)),
            start_date=start.isoformat(),
            planned_end_date=(start + timedelta(days=c["planned"] - 1)).isoformat(),
            audience=c["audience"], tracks_conversions=c["tracked"],
        ))
        n = (last - start).days + 1
        for i in range(n):
            d = start + timedelta(days=i)
            prog = i / max(n - 1, 1)
            m_ctr = 1 + c["drift"]["ctr"] * prog
            m_cvr = 1 + c["drift"]["cvr"] * prog
            m_cpm = 1 + c["drift"]["cpm"] * prog
            sh = c["shock"]
            if sh and (anchor - d).days < sh["days"]:
                m_ctr *= sh.get("ctr", 1.0)
                m_cvr *= sh.get("cvr", 1.0)
                m_cpm *= sh.get("cpm", 1.0)
            if d.weekday() >= 5:
                m_ctr *= .92
            spend = round(c["daily"] * rng.uniform(.88, 1.04), 2)
            imps = int(spend / (c["cpm"] * m_cpm) * 1000 * rng.uniform(.93, 1.07))
            clicks = int(imps * c["ctr"] * m_ctr * rng.uniform(.9, 1.1))
            reach = int(imps / (c["freq"] * (1 + .5 * prog)) * rng.uniform(.95, 1.05))
            conv = rev = None
            if c["tracked"]:
                conv = _stochastic_round(rng, max(0.0, clicks * c["cvr"] * m_cvr * rng.uniform(.75, 1.25)))
                rev = round(conv * c["value"] * rng.uniform(.85, 1.15), 2)
            daily.append(dict(campaign_id=c["id"], date=d.isoformat(), spend=spend,
                              impressions=imps, reach=reach, clicks=clicks,
                              conversions=conv, revenue=rev))
    return campaigns, daily


def _er(posts, platform, ctype):
    sel = [p for p in posts if p["platform"] == platform and p["content_type"] == ctype]
    reach = sum(p["reach"] for p in sel)
    eng = sum(p["likes"] + p["comments"] + p["shares"] + p["saves"] for p in sel)
    return (eng / reach if reach else 0.0), len(sel)


_TUNABLE = ("PLATFORM", "TYPE_REACH", "TYPE_ENG", "TOPIC_R", "PLATFORM_TYPE_ENG", "LINK_CTR", "CAMPAIGNS")
_LOCK = threading.Lock()


def _perturbed(seed: int) -> dict:
    """Randomly nudged copies of the tunable parameters, so a new seed shifts which formats,
    platforms and campaigns win. The same seed always gives the same variation."""
    r = random.Random(seed * 7919 + 13)
    j = lambda x, pct: x * (1 + r.uniform(-pct, pct))  # noqa: E731
    out = {k: copy.deepcopy(globals()[k]) for k in _TUNABLE}
    for p in out["PLATFORM"].values():
        p["reach"], p["er"] = j(p["reach"], .25), j(p["er"], .25)
        p["p"] = min(.9, j(p["p"], .20))
        if p["weekend_p"]:
            p["weekend_p"] = min(.9, j(p["weekend_p"], .20))
    for k in ("TYPE_REACH", "TYPE_ENG"):
        out[k] = {t: j(v, .30) for t, v in out[k].items()}
    out["TOPIC_R"] = {t: j(v, .20) for t, v in out["TOPIC_R"].items()}
    out["PLATFORM_TYPE_ENG"] = {k: j(v, .20) for k, v in out["PLATFORM_TYPE_ENG"].items()}
    out["LINK_CTR"] = {t: j(v, .25) for t, v in out["LINK_CTR"].items()}
    for c in out["CAMPAIGNS"]:
        c["daily"], c["cpm"], c["ctr"] = round(j(c["daily"], .30)), j(c["cpm"], .30), j(c["ctr"], .35)
        if c["tracked"]:
            c["cvr"], c["value"] = j(c["cvr"], .45), j(c["value"], .25)
        for k in c["drift"]:
            c["drift"][k] += r.uniform(-.15, .15)
    return out


def build_seed(anchor: date | None = None, seed: int | None = None) -> dict:
    """Build the demo dataset. seed=None gives the original data; any integer gives a randomised variant."""
    if seed is None:
        return _build_seed(anchor, None)
    with _LOCK:                                   # swap in the varied parameters, then restore
        saved = {k: globals()[k] for k in _TUNABLE}
        globals().update(_perturbed(seed))
        try:
            return _build_seed(anchor, seed)
        finally:
            globals().update(saved)


def _build_seed(anchor: date | None, seed: int | None) -> dict:
    anchor = anchor or date.today()
    rng = random.Random(20260 if seed is None else seed)
    campaigns, daily = _build_campaigns(rng, anchor)
    camp_by_id = {c["id"]: c for c in campaigns}
    camp_specs = {c["id"]: c for c in CAMPAIGNS}

    posts: list[dict] = []
    n = 0
    first = anchor - timedelta(days=HISTORY_DAYS - 1)
    for i in range(HISTORY_DAYS):
        d = first + timedelta(days=i)
        for platform, p in PLATFORM.items():
            prob = p["weekend_p"] if d.weekday() >= 5 else p["p"]
            if rng.random() >= prob:
                continue
            ctype = _weighted(rng, TYPE_WEIGHTS[platform])
            topic = rng.choice(TYPE_TOPICS[ctype])
            hour = _pick_hour(rng, platform)
            minute = rng.choice([0, 5, 10, 15, 20, 30, 40, 45])
            when = datetime.combine(d, time(hour, minute))
            caption = rng.choice(CAPTIONS[ctype]).format(t=topic.lower())
            campaign_id = None
            for cid, spec in camp_specs.items():
                c = camp_by_id[cid]
                end = anchor - timedelta(days=spec["end_ago"] or 0)
                if (spec["platform"] == platform and ctype in spec["link_types"]
                        and date.fromisoformat(c["start_date"]) <= d <= end and rng.random() < .55):
                    campaign_id = cid
                    break
            n += 1
            posts.append(dict(
                id=f"post_{n:03d}", caption=caption, platform=platform, content_type=ctype,
                topic=topic, status="published", created_at=when.isoformat(),
                published_at=when.isoformat(), scheduled_for=None,
                campaign_id=campaign_id, source="sample",
                **_make_post_metrics(rng, platform, ctype, topic, hour, d, anchor),
            ))

    published = list(posts)
    blank = dict(reach=None, impressions=None, likes=None, comments=None,
                 shares=None, saves=None, link_clicks=None, campaign_id=None)
    for platform, ctype, topic, caption, source, in_days in DRAFTS:
        n += 1
        sched = None
        if in_days:
            sched = datetime.combine(anchor + timedelta(days=in_days), time(10, 0)).isoformat()
        posts.append(dict(id=f"post_{n:03d}", caption=caption, platform=platform,
                          content_type=ctype, topic=topic, status="draft",
                          created_at=datetime.combine(anchor - timedelta(days=n % 4 + 1), time(14, 30)).isoformat(),
                          published_at=None, scheduled_for=sched, source=source, **blank))
    for platform, ctype, topic, caption, source, in_days, hour in PROPOSED:
        n += 1
        posts.append(dict(id=f"post_{n:03d}", caption=caption, platform=platform,
                          content_type=ctype, topic=topic, status="proposed",
                          created_at=datetime.combine(anchor - timedelta(days=1), time(16, 0)).isoformat(),
                          published_at=None,
                          scheduled_for=datetime.combine(anchor + timedelta(days=in_days), time(hour, 0)).isoformat(),
                          source=source, **blank))

    # Sample recommendation history, using numbers computed from the data above.
    ig_car, ig_n = _er(published, "Instagram", "carousel")
    li_tes, li_n = _er(published, "LinkedIn", "testimonial")
    fb_pro, fb_n = _er(published, "Facebook", "promotional")
    old = datetime.combine(anchor - timedelta(days=21), time(9, 0))
    recs = [
        dict(id="rec_hist_1", batch_id="batch_sample_1", priority=1, topic="Workflow templates",
             format="carousel", platform="Instagram",
             caption_brief="Share a swipeable set of reusable workflow templates.",
             reason="Instagram carousels have the highest engagement rate of any Instagram format in this dataset.",
             supporting_data=[dict(label="Instagram carousel engagement rate", value=f"{ig_car:.1%}"),
                              dict(label="Posts analysed", value=str(ig_n))],
             posting_window="Weekday evenings, 18:00-21:00", confidence="high",
             call_to_action="Save this checklist for your next planning session.",
             success_metric="Saves per post", is_test=False, status="saved", source="sample",
             created_at=old.isoformat(), saved_post_id=None),
        dict(id="rec_hist_2", batch_id="batch_sample_1", priority=2, topic="Customer onboarding",
             format="testimonial", platform="LinkedIn",
             caption_brief="Publish a customer story focused on a fast onboarding result.",
             reason="LinkedIn testimonials sit above the LinkedIn average for engagement.",
             supporting_data=[dict(label="LinkedIn testimonial engagement rate", value=f"{li_tes:.1%}"),
                              dict(label="Posts analysed", value=str(li_n))],
             posting_window="Tuesday to Thursday, 08:00-10:00", confidence="medium",
             call_to_action="Read the full story and book a demo.",
             success_metric="Link clicks", is_test=False, status="new", source="sample",
             created_at=old.isoformat(), saved_post_id=None),
        dict(id="rec_hist_3", batch_id="batch_sample_1", priority=3, topic="Product updates",
             format="promotional", platform="Facebook",
             caption_brief="Reduce repeated promotional posts and test a customer story instead.",
             reason="Facebook promotional posts have the lowest engagement of the formats published most often.",
             supporting_data=[dict(label="Facebook promotional engagement rate", value=f"{fb_pro:.1%}"),
                              dict(label="Posts analysed", value=str(fb_n))],
             posting_window=None, confidence="medium",
             call_to_action="See how teams use Brightloom.",
             success_metric="Engagement rate", is_test=True, status="dismissed", source="sample",
             created_at=old.isoformat(), saved_post_id=None),
    ]

    return dict(
        meta=dict(version=SEED_VERSION, anchor_date=anchor.isoformat(), seed=seed,
                  history_days=HISTORY_DAYS, generated_at=datetime.now().isoformat(timespec="seconds"),
                  business="Brightloom (fictional)",
                  note="All records are fictional demonstration data."),
        posts=posts, campaigns=campaigns, campaign_daily=daily, recommendations=recs,
    )
