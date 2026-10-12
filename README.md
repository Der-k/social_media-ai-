# Compass: AI-powered social media analytics and decisions (demo)

A local demonstration prototype inspired by Hootsuite. It reports what happened on social media
and in advertising, and (in later build stages) uses the evidence to recommend what to publish next.

**All data is fictional.** The company "Brightloom" does not exist. No social media or ad accounts
are connected, nothing is published, and no budgets are changed.

## Build status

| Stage | Scope | Status |
|---|---|---|
| 1 | Setup, FastAPI entry point, layout and navigation, seed data and storage, Overview dashboard | **Done** |
| 2 | Social Analytics page | **Done** |
| 3 | Advertising Performance (campaign table, detail, compare, "Analyze Campaign with AI") | Next |
| 4 | Content Library (search, filter, sort, post detail, best/worst, add/edit/delete drafts) | **Done** |
| 5 | AI Recommendations (Groq, Pydantic-validated JSON, caching, save as draft) | **Done** |
| 6 | AI Assistant: data Q&A and AI post generator (Groq) | **Done** |
| 7 | Content Calendar | Planned |
| 8 | Simulated real-time updates (pause/resume, alerts) | Planned |

## Windows setup (PowerShell)

```powershell
cd social_media_ai
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

If PowerShell blocks activation, run once: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.
In Command Prompt use `.venv\Scripts\activate.bat` instead.

The Overview works without a Groq key. For AI features (later stages), edit `.env`:

```env
GROQ_API_KEY=your_key_from_console.groq.com
GROQ_MODEL=a_currently_supported_model_id
```

The key stays on the server and is never sent to the browser. `.env` is git-ignored.
The browser loads Tailwind, Chart.js and the Figtree font from CDNs, so the first page load needs internet access.

## Randomising the data

The dice button in the top bar (and Settings, with an optional seed) regenerates all dummy values:
post metrics, campaign spend and conversions, and the underlying tendencies (which formats, platforms and
campaigns win). Your own drafts are kept; recommendations restart. The top bar shows "Randomised data ·
seed N". Settings, **Reset demo data** restores the original dataset.

## Resetting the demo

Settings, then **Reset demo data**. Or delete `instance/demo_state.json` and restart.
The sample data is anchored to the date it was first generated, and every page treats that date as
"today", so the demo stays internally consistent even if you open it weeks later.

## Architecture

```
app/
  core/config.py                  settings from .env
  data/seed.py                    deterministic fictional data generator
  data/storage.py                 JSON-file store (atomic writes, lock, reset)
  schemas/                        Pydantic v2 models (posts, campaigns, recommendations)
  repositories/                   data access and the shared platform/campaign/date filters
  services/metrics.py             pure calculations: safe_div, CPC, CPA, ROAS, engagement rate
  services/analytics_service.py   dashboard payload (KPIs, series, insights)
  web/routes.py                   HTTP routes: pages and JSON endpoints
  templates/, static/             Jinja2 + Tailwind (CDN) + vanilla JS + Chart.js (CDN)
```

## Social Analytics

Organic (published-post) performance, from the same posts and `metrics.py` functions as the dashboard.
Date range, platform and campaign filters apply and update the page in place.

- 8 organic KPIs with change vs the previous period and sparklines, and rule-based "what stands out" findings
- Platform scorecards (always compare all four platforms; the selected one is highlighted)
- Engagement-rate trend by platform (daily up to 14 days, otherwise 7-day periods ending on the last day;
  a shorter first period is labelled so every post is counted), publishing cadence against engagement rate
- Engagement mix (likes, comments, shares, saves) by platform or by format
- Reach vs engagement scatter, one dot per post with average lines. Click a dot to open the post
- Sortable format table, topic chart, format-by-platform matrix (vs each platform's own average)
- Posting-time heatmap (switch between engagement rate, reach per post and post count) and best windows
  per platform. Both use all history, because a date range alone has too few posts per time slot
- "Ask the AI to explain this" opens the AI Assistant with a prefilled question. It is never sent automatically

Groups under 3 posts are shown faded and marked thin. Rates with no data show a dash, never 0.

## AI Recommendations

The core feature: it does not just report what happened, it recommends what to publish next.

**How it works** (the order from the project brief):

1. Retrieve all published posts and campaign records.
2. Calculate every metric in Python.
3. Find high performers and under-performers.
4. Compare by platform, format, topic and posting time.
5. Boil the findings down to numbered **candidates** (publish more, reduce, repurpose across platforms,
   run a test, support or probe a campaign), each with its own measured evidence and confidence.
6. Send that compact summary (about 8,000 characters) to Groq.
7. The model **chooses, prioritises and words** 3-5 candidates as JSON, validated with Pydantic.
8. Python attaches the supporting data, confidence and posting window. The page shows each
   recommendation next to the data behind it.
9. **Save as draft** puts it in the Content Library, labelled as AI-created.

**What the AI cannot do.** It cannot change a platform or format, set confidence, supply statistics
or invent a candidate. Numbers in its wording are checked against the evidence, and wording that quotes
anything unverified is replaced with standard wording (the card says so). It cannot publish or touch
budgets. Thin evidence is shown as **a test, not a trend**, and a candidate that duplicates an existing
draft is flagged "already in your pipeline".

**Confidence** is calculated in Python from sample size, size of the effect and consistency
(for example, "12 posts, 83% at or above the platform average").

**Caching.** Generating again with unchanged data makes no API call ("Analyse again anyway" forces
it). Saving a draft changes the pipeline, so the next run re-analyses. The AI reply is also cached for
15 minutes.

**Without Groq.** The page and evidence still work. "Rule-based only" produces the same structure with
standard wording and no API call, clearly labelled. Failures are never replaced with made-up output.

## AI Assistant (Groq)

Two tools on one page:

- **Ask about your data.** Natural-language questions answered from a compact fact sheet. Python
  computes every number; keyword retrieval sends only the 1-3 relevant sections (KPIs, platforms,
  formats, topics, posting times, campaigns, changes, top/weakest posts, drafts) up to a 7,000
  character cap. The prompt forbids inventing metrics, requires "Hypothesis:" labels for guesses, and
  treats "not tracked" as different from zero. Each answer shows which sections it used.
- **Draft a post.** Choose topic, platform, format, audience, objective and tone. The server calculates
  the evidence (platform average, format and topic performance, best time of day) and the model writes
  hook, body, call to action, hashtags and an explanation of how the draft follows that evidence. The
  reply must be valid JSON matching a Pydantic model or it is rejected. With under 3 comparable posts the
  draft is flagged as a test. You edit the text and save it as a draft (or a proposed post if you pick a
  date), labelled as AI-created. Nothing is published.

Safeguards in `services/ai_service.py`: the key stays server-side; 15-minute response cache;
10 calls/minute local guard; capped question, history and context sizes; every Groq failure
(missing/invalid key, rate limit, timeout, no network, retired model, bad output) becomes a plain
message and never a fake answer. The dashboard and every other page work without Groq.
**Settings, Test Groq connection** checks the key and model without generating text.

Configuration is in `.env` (see `.env.example`): `GROQ_API_KEY`, `GROQ_MODEL` (currently
`openai/gpt-oss-120b`), optional `GROQ_TIMEOUT_SECONDS`. Change them and restart the server.

## Content Library

- Search, filter by format, topic and status, sort, and page through posts. The topbar date range,
  platform filter and the campaign selector apply as well.
- Best and weakest performers use the dashboard's rule (engagement rate, posts with 1,000+ reach).
- **Strong / Weak** compares a post's engagement rate with its own platform's average (25% above or below).
- Each post page benchmarks the post against its platform and against the same format on that platform.
  With fewer than 3 comparable posts it says so instead of showing an average. For drafts the same
  table is shown as a reference of what similar published posts achieved, not a forecast.
- Drafts and proposed posts can be created, edited and deleted. Published sample posts are read-only.
  Nothing is ever sent to a social platform.
- Validation runs on the server (Pydantic plus business rules such as "a campaign must run on the
  post's platform") and is shown next to the field.

### How numbers stay consistent

Posts and daily ad rows are the only source records. KPI cards, charts, the heatmap, insights and
alerts are all computed from them through `services/metrics.py`; nothing on a page is hard-coded.

Definitions:

- Engagement rate = (likes + comments + shares + saves) / reach, organic posts only
- Total reach, impressions and link clicks = organic + paid. Paid reach is the sum of daily reach, so
  it can overcount people reached on several days (a demo simplification)
- CPC = spend / clicks, CPA = spend / conversions, ROAS = attributed revenue / spend
- Undefined results (zero denominator) are `None`, shown as an em dash, never 0
- `None` conversions or revenue means **not tracked** (for example the awareness campaign), which is
  different from 0 (tracked, none occurred). CPA and ROAS use only spend from rows where the outcome
  is tracked

### Filters

Date range, platform and campaign live in the query string (`?days=30&platform=all&campaign=all`)
and carry across every page. Two views deliberately ignore one filter and say so on the page: the
posting-time heatmap uses all 90 days (more posts per cell), and the platform comparison chart
ignores the platform filter (so platforms can be compared).
