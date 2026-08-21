# Trading Engine — Project Specifications

> **Status: v2 rebuild in progress.**
> The project is pivoting from a *watchlist tick-monitor* (Alpaca streaming, small
> symbol list) to a **pre-market universe scanner** (FMP data, scheduled scans over the
> full US equity universe). Read the "Architecture Pivot" section before making changes.

---

## 1. Product Definition

**What it is:** An **alerts-only** pre-market stock scanner. It scans the US equity
universe during the pre-market session and surfaces a short list of candidates where a
~5% intraday move is *structurally plausible*, delivered to a web dashboard the end user
opens on desktop or phone.

**What it is NOT:**
- It does **not** execute trades. No broker integration, no order placement.
- It does **not** predict or promise a 5% gain. It filters *candidates*; the "5%" is a
  feasibility screen, not a forecast. All UI language must reflect this.
- It is **not** financial advice. It is a decision-support tool.

**End user:** A single non-technical trader (project owner's friend) who accesses the
deployed dashboard by URL.

---

## 2. Architecture Pivot (v1 → v2)

| Dimension | v1 (current code) | v2 (target) |
|---|---|---|
| Data source | Alpaca (REST + WebSocket) | **FMP (Financial Modeling Prep)** |
| Scope | ~10 user-picked symbols | **Full US equity universe (~6,000+)** |
| Trigger model | Continuous tick stream | **Scheduled pre-market scans (cron)** |
| Logic | YAML per-tick rule engine | **3-stage filtration pipeline** |
| Fundamentals | None | **Float, 20d avg volume, SMAs, resistance** |
| DB (local) | SQLite | **PostgreSQL** |
| DB (prod) | Render PostgreSQL | **Supabase PostgreSQL** |
| Frontend host | Render static site | **Vercel** |
| Trading | Alpaca MCP (paper/live) | **Removed — alerts only** |

### Why Alpaca was dropped
Alpaca's free plan caps the WebSocket at 30 symbols, serves REST market data with a
15-minute delay, and its real-time feed is IEX-only (~2–3% of consolidated volume).
Critically, **Alpaca provides no float or short-interest data on any plan**, and
`Static_Float` is the very first filter in the pipeline. Since the user does not trade,
the broker relationship has no remaining value. FMP supplies price + volume + float +
screener + news in one provider.

### What survives from v1 (~30–40%)
Keep and reuse: the React/Vite/Zustand frontend shell, the client-facing WebSocket
broadcast channel, the FastAPI app skeleton, the alert persistence + broadcast pattern,
Alembic setup, the test harness, and CI/CD.

### What is replaced (~60–70%)
Retire: `alpaca_client.py`, `stream_manager.py`, the watchlist-streaming model, and the
per-tick YAML `rule_engine` as the primary trigger path. The 3-stage scanner replaces it.
Thresholds remain **externally configurable** (YAML/env) so they can be tuned without a
redeploy.

---

## 3. Tech Stack (v2)

- **Backend**: FastAPI (Python 3.10+), `uv`, async SQLAlchemy, Alembic
- **Frontend**: React 19 + Vite + Zustand + Tailwind
- **Database**: PostgreSQL everywhere (local Docker → Supabase in prod)
- **Market data**: FMP (REST + WebSocket + screener + float + news)
- **Scheduling**: Render Cron Job (UTC — DST handled explicitly in code)
- **Real-time to browser**: WebSocket
- **API contract**: Design-first OpenAPI (`openapi/spec.yaml`)

### Deployment topology
```
Vercel (frontend, static)
   │  HTTPS + WSS
   ▼
Render Web Service (always-on: REST API + client WebSocket)
   │
   ├── Render Cron Job (pre-market scanner, 4:15–9:25 AM ET, tiered)
   │        │
   │        └──> FMP API
   ▼
Supabase PostgreSQL
```

---

## 4. The Scanner Specification

### 4.1 Data dictionary

| Field | Meaning | Source | Refresh |
|---|---|---|---|
| `static_float` | Shares available to trade | FMP All Shares Float | Nightly |
| `volume_avg_20d` | 20-day SMA of daily volume | FMP historical daily | Nightly |
| `price_close_yesterday` | Prior regular-session close | FMP daily quote | Nightly |
| `high_yesterday` | Prior session high | FMP historical daily | Nightly |
| `high_20d` | 20-day high | FMP historical daily | Nightly |
| `sma_50`, `sma_200` | 50/200-day SMAs | FMP historical daily | Nightly |
| `premarket_volume_profile` | Cumulative premarket volume by 5-min bucket from 04:00 ET, averaged over 20 sessions | FMP intraday (extended hours) | Nightly |
| `price_premarket_current` | Live premarket price | FMP real-time quote | Live |
| `volume_premarket_accumulated` | Volume traded since 04:00 ET today | FMP intraday bars | Live |
| `catalyst` | News / earnings tag | FMP news + earnings calendar | Live (Phase 4) |

### 4.2 Derived metrics

```
gap_pct            = (price_premarket_current - price_close_yesterday) / price_close_yesterday * 100
rvol_pct           = volume_premarket_accumulated / expected_volume_at_this_time_of_day * 100
nearest_resistance = min( high_yesterday, high_20d, sma_50, sma_200 )  # of those ABOVE current price
upside_pct         = (nearest_resistance - price_premarket_current) / price_premarket_current * 100
```

> **RVOL is time-of-day normalized.** `expected_volume_at_this_time_of_day` comes from
> `premarket_volume_profile` — the average cumulative premarket volume this ticker had
> reached by this same clock time over the last 20 sessions. This is deliberately more
> accurate (and more expensive) than dividing by the full-day 20d average.

### 4.3 The three stages

**Stage 1 — Structural liquidity (nightly + at scan start)**
- `static_float < 75,000,000`
- `volume_avg_20d > 500,000`
- Executed as a SQL query against the pre-computed reference table.

**Stage 2 — Momentum engine (every scheduled pass, 04:15 → 09:25 ET — see 4.5)**
- `3.0 <= gap_pct <= 15.0`
- `rvol_pct > 10.0`

**Stage 3 — Room-to-run (computed every pass; 09:25 is the authoritative run)**
- `upside_pct >= 5.5` (5% target + 0.5% slippage/fee buffer)

> **Breakout convention — decided, revisit later.** A ticker trading *above all four*
> resistance levels is **rejected** ("headroom unmeasurable"). With no ceiling above it,
> upside cannot be computed, and the conservative reading is to skip rather than invent an
> unbounded value.
>
> This is a **strategy choice by the end user, not a technical constraint.** Such a stock is
> arguably in "blue-sky" breakout territory with no overhead supply — which some would treat
> as the *strongest* gap-and-go setup, not the weakest. Deliberately deferred until live V2
> experience shows how often it occurs and how those names behave. See open question #8 in
> `PROJECT_REPORT.md`.
>
> **How often it occurs is now measured: 46 times in 8 sessions — 17.7% of Stage-2
> survivors, ~5.75 a morning** (21 August 2026, authoritative passes only). Nearly one in
> five tickers that clears gap *and* RVOL is discarded for having no measurable ceiling.
> That is large enough that the decision deserves to be taken deliberately rather than left
> as a default. **How those names behave is still unknown** — the second half of the
> deferral needs Phase 6 outcome labelling, and these tickers are rejected before an alert
> exists, so today nothing records what they did next. Note the corollary: this rejection is
> exactly why `upside_pct IS NULL` has never once appeared on a live alert, so the
> null-tolerance below remains insurance rather than an exercised path.
>
> **Keep this cheap to reverse.** `Candidate.upside_pct` and `nearest_resistance` are
> nullable by design. The alternative behaviours (alert with upside marked unbounded, or
> assign a synthetic extension target) must stay a change to the Stage-3 branch plus a
> config flag — never a change to the alert schema, the scoring signature, or the UI
> contract. Therefore **all downstream code (scoring, API, dashboard) must tolerate a null
> `upside_pct` / `nearest_resistance` from the start.**

**Risk filters (block the alert regardless of the above)**
- Minimum price floor (configurable; default $2 — sub-$2 names hit 5% on noise)
- Minimum dollar volume (configurable — avoids untradeable thinness)
- Market-wide condition check (index tape context; a red tape lowers confidence)
- Halt risk flag (best-effort, Phase 4)

### 4.4 Alert output contract

Every alert carries: `ticker`, `gap_pct`, `rvol_pct`, `catalyst` (nullable),
`confidence_score`, `suggested_entry_window`, `entry_reference_price`,
`nearest_resistance`, `upside_pct`, `scan_timestamp`.

> **Confidence score:** starts as a transparent, documented weighted formula with
> constants in config. The weights are **provisional assumptions until backtested**
> (Phase 6). The UI must never present the score as validated.

> **What the score does and does not say, measured over 61 live alerts** (21 August 2026).
> It is a **within-session ordering, not a quality measure.** The top score sits in a
> 0.893–0.924 band on every session regardless of conditions — the factors saturate by
> design, so a 3-candidate morning and a 14-candidate one both produce a ~0.90 leader.
> "0.91" therefore says *best today*, never *good*. Two further facts constrain how the
> weights may be refitted:
>
> - **`data_quality` is a constant.** It scored 1.000 on all 61 alerts — on Premium with
>   100% profile coverage none of its penalties apply — so its 10% weight is a fixed
>   +0.100 offset that cannot rank anything. It remains a real guard for degraded data;
>   it simply never discriminates on a normal morning.
> - **Weight and influence are mismatched.** By weight × observed spread, RVOL (37.6%) and
>   upside (35.0%) drive ~73% of the ordering, liquidity 15.9%, and `gap_position` just
>   11.4% against its 20% weight.
>
> The practical consequence is a **compressing head**: the more candidates a morning
> produces, the less the top of the list separates (0.206 between rank 1 and rank 5 at 8
> candidates, 0.074 at 14). The ranking is weakest precisely on the mornings the user most
> depends on it. Phase 6 fits against this, not just against hit rates.

### 4.5 Timing model

Scans run on a **tiered cadence from 04:15 to 09:25 ET**, 19 passes a session. Each run is
**stateless**: it recomputes accumulated premarket volume by summing intraday bars from
04:00 ET to now, rather than carrying state between runs. All three stages run on every
pass — Stage 3 is pure arithmetic over data already in memory, so the upside figure is
available throughout the session. The **09:25 run is the authoritative pass**
(`is_final_pass`), and it is the one that pushes the definitive alert set.

| From  | Until | Interval | Passes |
|-------|-------|---------:|-------:|
| 04:15 | 07:00 |   60 min |      3 |
| 07:00 | 08:00 |   30 min |      2 |
| 08:00 | 08:30 |   15 min |      2 |
| 08:30 | 09:25 |    5 min |     12 |

The tiers are config (`SCAN_CADENCE_TIERS`), and the **first tier's start is also when the
window opens** — one value, so the two cannot drift. The shape was measured over six live
sessions (10–14, 17 August 2026; 394 completed passes) with `scripts/cadence_profile.py`:

- **04:00, 04:05 and 04:10 produced a Stage 2 survivor in none of 18 session-passes.** Not
  a quiet market — a structural impossibility. A bar is provisional until
  `BAR_SETTLE_MINUTES` after it closes, so the 04:00 bar is not trusted until ~04:12.
- **Half the session's passes carried a seventh of its information.** The 32 passes from
  04:25 to 06:55 surface ~1.4 tickers a session that are still candidates at 09:25.
- **The last 40 minutes are the opposite** — 73% of what they surface first survives to the
  final pass. That is the confirmation window and it stays at 5 minutes.

> **Cadence cannot change the alert set, because scans are stateless.** The 09:25 pass
> recomputes every ticker from all bars since 04:00 independent of what ran before it, and
> alerts dedup per `(ticker, session)`. Coarsening the early session changes dashboard
> freshness before 09:25 and the completeness of the faded record — nothing else. Two
> guarantees make that structural rather than incidental: the slot list **always ends at
> 09:25** whatever the tiers say, and the volume-profile bucket epoch stays **04:00** in
> `bars.bucket_minute` rather than following the window start, so moving the open to 04:15
> cannot rebase the RVOL denominator.

> **Measured bandwidth** (`scan_runs` summed per ET session, 21 August 2026): **46.3 MB a
> session at 66 passes, 20.6 MB at 19** — a **55% cut, not the 71% the pass count
> suggests**, because the fan-out asks for every bar since 04:00 and the passes kept are the
> late, expensive ones. Against 50 GB / 30 days the live scan is ~2.0% before and **~0.9%**
> after. Phase 4C's "~47% of allowance" was a projection from a 10.2 MB `--at` replay pass
> and does not survive per-pass measurement; see `docs/PLAN.md` Phase 4C.

> **The scan is not where the bandwidth goes.** The nightly reference cycle is **~92% of
> everything this project consumes** — ~245 MB a night against the scan's 20.6 MB a
> session. Total draw is **~11.4% of the 50 GB allowance** (was 20.8% before the 18 August
> incremental profile build). Ample headroom, but it means the cadence and window work
> optimised the small half; `docs/PLAN.md` Phase 4B carries the correction and the reason
> the old figure read 1.1%.

> **The gap is payload, not calls.** A live pass makes **737 calls** (18 August 2026, seven
> sessions) against 4C's 672 — the Stage-1 set grew ~10%, so per call it is 15.2 KB in the
> replay against 2.27 KB live at 09:25. Calls are also where the tiering buys the real
> headroom against the guard: 66 passes is ~48.6k calls a day against the cron's
> `FMP_DAILY_BUDGET=80000`, 19 passes is ~14.0k. **Every pass makes the same number of
> calls** — 737.0 on all 66 passes of 17 August — because the fan-out is one call per
> Stage-1 survivor and that set is fixed for the session. The ceiling is shared: both crons
> increment the same `api_budget` row for the UTC day, so the old cadence plus a nightly
> peaked at **56,011 calls, 70% of 80,000**. It is now 24%.

> **Render cron is UTC.** ET/DST conversion must be explicit in code. A UTC-pinned
> schedule silently drifts by one hour twice a year — for a market-timed scanner this is
> a correctness bug, not a cosmetic one. Schedule generously in UTC and gate the actual
> work on a computed ET timestamp.

> **The window bounds are minutes, not instants.** 04:15–09:25 means exactly that, so
> the gate truncates to whole minutes before comparing (`clock.at_minute`). Render starts
> a job 10–45 s after its scheduled minute; comparing full timestamps made the 09:25
> authoritative pass begin at 09:25:10 and be rejected as outside a window ending at
> 09:25, while the log header — rendered at minute resolution — printed "09:25". The
> value shown and the value decided on must be the same value. This is a resolution
> choice, not a grace period: 09:26:00 is still outside.

Wake-ups that do no work write a `scan_runs` row with `status='skipped'`, zero counts and a
`skip_reason`: **`outside_window`** beyond 04:15–09:25, or **`off_cadence`** inside the
window on a minute the tiers decline. They are the cron's heartbeat: without them, "the
cron fired and correctly skipped" and "the cron never fired" are the same empty query, and
only Render's logs — which expire — can separate them.

The tiered cadence makes heartbeats the *majority* of wake-ups — ~65 of a weekday's 84
against 19 scans — and they now land between the morning's passes rather than only after
the close. Three things keep that from hiding the morning's result: `/status` computes
health from the last run that **attempted work**, it also returns **`last_wake_up_at`** so
"the cron is alive" stays answerable when the last scan is an hour old by design, and the
Scans page lists **attempted runs only** (`GET /scanner/scan-runs?attempted_only=true`;
unfiltered by default, which is where "did the cron fire?" is answered).

> **A session total is not a scan result.** Alerts dedup per `(ticker, session_date)` and
> are updated in place across the morning's 19 passes, so the alert count is "distinct
> tickers that qualified at some point since 04:00" — not what the last scan found. On 14
> August 2026 that was 37 against 11 still qualifying at 09:25, and the status panel
> headlined the 37 as the last scan's result directly above a funnel ending in 11.
> `/status` therefore returns `alert_count` and `confirmed_count` separately, plus
> `final_pass_complete`: before 09:25 nothing is confirmed **yet**, which is a different
> statement from a confirmed count of zero. The dashboard shows the confirmed set first
> and the faded ones behind a toggle, split on the alert's own `is_final_pass` — never by
> parsing `suggested_entry_window`, which is prose for a human. Faded candidates are
> demoted, never dropped: a ticker that spiked at 05:10 and died is real information, and
> Phase 6 outcome labelling will want it.
>
> **The 37-against-11 was not an unlucky example — it is the normal shape.** Across seven
> live sessions (13–21 August 2026) only **21–42% of a session's alerts survive to 09:25**:
> 14–41 tickers qualify at some point, **3–14** remain. The toggle is therefore demoting
> roughly seven rows in ten, which is most of what keeps the page readable. A build that
> reverted to one undifferentiated list would not look slightly worse; it would show the
> user three times the rows, mostly dead.

---

## 5. Database Schema (v2)

**New tables**
1. `universe` — ticker, name, exchange, is_active, last_refreshed
2. `reference_data` — ticker (FK), static_float, volume_avg_20d, price_close_yesterday,
   high_yesterday, high_20d, sma_50, sma_200, computed_at
3. `premarket_volume_profile` — ticker (FK), bucket_minute (minutes from 04:00),
   avg_cumulative_volume, sessions_sampled, computed_at
4. `scan_runs` — id, started_at, finished_at, stage_counts_json, status, profile,
   api_calls_used, error
5. `scanner_settings` — singleton row holding the user's threshold/profile overrides
   (id, profile, overrides_json, updated_at)
6. `alerts` — ticker, session_date, scan_timestamp, scan_run_id (FK), profile, gap_pct,
   rvol_pct, rvol_mode, rvol_is_approximate, catalyst, entry_reference_price,
   nearest_resistance, resistance_source, upside_pct, suggested_entry_window,
   confidence_score, score_breakdown_json, is_final_pass, is_read, created_at, updated_at
7. `scan_observations` — one row per (scan_run, ticker): the Stage-2 inputs and outputs,
   the stage reached, the rejection reason, and **copies** of the reference values that
   were its denominators
8. `premarket_session_volume` — one row per (ticker, session): the cumulative pre-market
   volume curve that session contributed to the profile average

> **`premarket_session_volume` exists because an average cannot be rolled forward.**
> `premarket_volume_profile` stores only `avg_cumulative_volume`, and "add the newest
> session, drop the oldest" needs the departing session's contribution. Worse, the average
> is taken **per bucket** — over the sessions that actually reached it — so there is not
> even a single divisor to work backwards from. Keeping the curves makes a fresh night
> cost **one request per ticker** instead of a full 20-session refetch.
>
> It does not probe backwards to fill a short history. A history shorter than
> `profile_sessions_target` is almost always a young listing rather than an interrupted
> build, and stored data cannot tell those apart, so nightly back-probing would spend real
> calls rediscovering that a young ticker is still young. **`--rebuild` is the repair
> path**, and the answer when `profile_sessions_target` is raised.
>
> A session that traded only in regular hours is stored with an **empty** bucket map, not
> dropped: it still counts toward `sessions_sampled`, and storing it is what stops the
> forward cursor re-fetching that day every night.

> **`scan_observations` copies the denominators instead of joining to them.** That
> duplication is the point. `reference_data` is one current row per ticker and
> `premarket_volume_profile` is unique per `(ticker, bucket_minute)` — both rebuilt
> nightly — so a join at read time answers with tonight's numbers rather than the ones the
> decision was made from. Re-fetching the bars does not help either: 49.4% of pre-market
> bars are revised upward within ~7 minutes of closing.
>
> Written at the **09:25 pass for every Stage-1 survivor** (~741) and at anchor passes
> (04:15, 07:00, 08:30) for candidates only. The full write is what makes Phase 6's
> threshold sensitivity sweep possible: a sweep asks about the tickers the scanner
> **rejected**, and `stage_counts_json` records those as a reason with no numbers.
>
> **NULL means not evaluated, never zero.** The stages short-circuit, so a ticker rejected
> on gap has no RVOL. A sweep that widens the gap band must report such tickers as
> unresolved rather than as passing — see `sweep_limitations()` in
> `app/services/scanner/observations.py`.

**Nothing is retained from v1.** `rules` and `watchlist` are both gone; the six tables
above are the whole schema.

> **`watchlist` was dropped after Phase 3.5.** It described a curated list of symbols to
> stream quotes for — a v1 concept. The v2 scanner's premise is the opposite: filter the
> whole universe every morning, so a favourites list plays no part in producing alerts.
> It had no UI, no mention elsewhere in this spec and no reader outside its own CRUD
> endpoints, while still having to be considered on every schema change. Git keeps it if
> a favourites feature ever earns a place on the roadmap.

> **`rules` was dropped in Phase 3.5.** This section previously said `rules` would hold
> tunable scanner thresholds. Phase 3 built `scanner_settings` for exactly that — typed
> columns, validated on write, with an env-default fallback — which left `rules` holding
> free-text `config_yaml` for the retired per-tick engine and read by nothing. It was
> dropped along with the rule engine, its API, its schemas and the `alerts.rule_id` FK.
>
> **`alerts` no longer carries any v1 columns.** `rule_id`, `setup_type`, `entry_price`,
> `stop_loss`, `target_price` and `market_data_json` were dropped, and the storage column
> `symbol` was renamed to `ticker` so storage and the section 4.4 contract agree. The
> mapping layer in `app/schemas/scanner.py` is gone.
>
> That migration deletes v1-origin alert rows (`session_date IS NULL`) rather than
> keeping them: every column that gave them meaning is dropped by the same migration,
> and both read paths filter on `session_date`, so they would be unreachable husks. The
> reasoning and the rollback semantics are in the docstring of
> `backend/alembic/versions/c653a931ecaf_*.py` and in README.md under "Rolling back".

---

## 6. Environment Variables

```bash
# Backend (backend/.env)
APP_ENV=development
DEBUG=true
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/trading_engine
FMP_API_KEY=your_fmp_key
FMP_BASE_URL=https://financialmodelingprep.com
CORS_ORIGINS=http://localhost:5173
SCANNER_TIMEZONE=America/New_York
SCANNER_ENABLED=true

# FMP client + budget guard.
# Premium (from 5 Aug 2026) has NO daily call cap: the limits are 750 calls/minute and
# 50 GB per rolling 30 days. The ceiling below is therefore runaway protection, not a
# vendor limit — bandwidth is what can actually end a month early, and it is tracked in
# `api_budget.bytes_used`.
FMP_DAILY_BUDGET=20000
FMP_MONTHLY_BANDWIDTH_GB=50
FMP_BANDWIDTH_WARN_PCT=80
FMP_TIMEOUT_SECONDS=20
FMP_MAX_RETRIES=3
FMP_RETRY_BACKOFF_SECONDS=1.0
FMP_FIXTURES_DIR=tests/fixtures/fmp

# Nightly reference refresh. `historical-price-eod/full` returns everything (1,254 bars
# for AAPL); the deepest metric is SMA-200, so the request is bounded server-side.
# Measured: 231 KB -> 51 KB per ticker, which across the universe is 19.2 -> 4.2 GB/month.
REFERENCE_HISTORY_DAYS=400

# Bar settling. Phase 4A measured that 49.4% of pre-market bars are revised UPWARD after
# publication (median +24.2%), all settling within 7 minutes of the bar closing. A bar
# younger than this is provisional. NOT hardcoded: 7 minutes is one session's measurement.
BAR_SETTLE_MINUTES=7

# Universe build. The Stage-1 size is DISCOVERED nightly, never configured; these only
# bound what counts as a surprise worth warning about.
UNIVERSE_SIZE_CEILING=3500
UNIVERSE_SIZE_MOVE_PCT=50
UNIVERSE_PRICE_MARGIN_PCT=20

# Pre-market volume profiles (the denominator for normalized RVOL).
PROFILE_SESSIONS_TARGET=20
PROFILE_SESSIONS_MIN=10
PROFILE_FETCH_DAYS_PER_REQUEST=7

# RVOL implementation: simple | normalized.
# `normalized` needs `premarket_volume_profile`, which Phase 4B populates — the data is
# available on Premium today. Switching the mode over is Phase 4C.
RVOL_MODE=simple

# Scanner thresholds (tunable without redeploy)
SCAN_FLOAT_MAX=75000000
SCAN_AVG_VOLUME_MIN=500000
SCAN_GAP_MIN=3.0
SCAN_GAP_MAX=15.0
SCAN_RVOL_MIN=10.0
SCAN_UPSIDE_MIN=5.5
SCAN_PRICE_FLOOR=2.0
SCAN_DOLLAR_VOLUME_MIN=1000000

# Threshold profile: production | demo (demo loosens ONLY the float cap)
SCAN_PROFILE=production
SCAN_DEMO_FLOAT_MAX=20000000000
SCAN_SNAPSHOT_FIXTURE=tests/fixtures/snapshots/demo_session.json

# Frontend (Vercel env)
VITE_API_URL=http://localhost:8000
VITE_WS_URL=ws://localhost:8000
```

> No hardcoded `onrender.com` URLs anywhere in frontend source. No secrets in
> `render.yaml` or committed files.

---

## 7. How to Run (Development)

```bash
# 1. Database
docker compose -f docker-compose.dev.yml up -d

# 2. Backend
cd backend
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload --port 8000     # http://localhost:8000/docs

# 3. Frontend
cd frontend
npm install
npm run dev                                          # http://localhost:5173
```

### Smoke tests (no live market data required)
```bash
cd backend
uv run python scripts/seed_test_alerts.py            # sample alerts into the dashboard
uv run python scripts/refresh_reference_data.py --fixture --force --tickers AAPL

# Scanner (no API calls — Stage 2 is fed by a snapshot scenario)
uv run python scripts/run_scan.py --fixture --profile demo --at "2026-07-28 08:45 ET"
uv run python scripts/run_scan.py --fixture --profile production --at "2026-07-28 09:25"
uv run python scripts/run_scan.py --fixture --profile demo --verbose   # per-ticker rejections
```

### FMP data pipeline (spends API budget and bandwidth)

The nightly cycle, in order. Each step is independently re-runnable and idempotent within
the same day, so a failure part-way is resumed by re-running the same command.

```bash
cd backend
uv run python scripts/build_universe.py              # ~11 calls: screener + bulk float
uv run python scripts/refresh_reference_data.py      # 1 call per ticker (float is bulk)
uv run python scripts/build_volume_profiles.py       # ~4 calls per Stage-1 ticker
```

Read-back and inspection, all free:

```bash
uv run python scripts/fmp_budget.py                  # calls, bytes, 30-day bandwidth
uv run python scripts/build_universe.py --show       # universe + recent build history
uv run python scripts/build_volume_profiles.py --show
uv run python scripts/build_universe.py --dry-run    # fetches, writes nothing
```

Legacy and maintenance:

```bash
uv run python scripts/probe_fmp_symbols.py           # V1 free-tier symbol probe
uv run python scripts/record_fmp_fixtures.py         # re-record test fixtures
```

> **`probe_fmp_symbols.py` is a V1 artefact.** It discovered which symbols the *free* tier
> would serve. On Premium every US symbol is served, so the universe comes from
> `build_universe.py` instead; the probe is kept only because `is_accessible_free_tier`
> still gates the refresh query.

### Tests
```bash
cd backend  && uv run pytest -v
cd frontend && npm test
```

---

## 8. Testing Strategy for the Scanner

Market-hours dependency makes naive testing impossible. Rules:
- **Record fixtures**: capture real FMP responses once, replay them in tests. Never hit
  the live API in CI.
- **Golden-case tests**: hand-built tickers that must pass/fail each stage boundary
  (gap exactly 3.0 / 15.0, rvol 10.0, upside 5.5) to pin inclusive-vs-exclusive edges.
- **Time injection**: the scanner takes an injectable "now" so any point in the
  04:15–09:25 window can be simulated. Never call `datetime.now()` directly in logic.
- **DST tests**: assert correct ET resolution on both sides of both DST transitions.

---

## 9. Design Decisions

- **Alerts-only**: no trade execution, ever. Keeps scope, cost, and liability contained.
- **Scheduled scans over streaming**: universe-wide scanning cannot be expressed as a
  symbol subscription; cron is both correct and cheaper.
- **Pre-computed reference data**: the nightly job is what makes a 6,000-ticker morning
  scan fit inside rate limits and a 25-minute window.
- **Stateless scan runs**: each run recomputes from bars. Simpler, crash-tolerant, and
  cron-friendly (no shared state between invocations).
- **Thresholds in config, not code**: the end user's strategy will evolve; tuning must
  not require a deploy.
- **Postgres everywhere**: removes the class of bugs where SQLite dev diverges from
  Postgres prod.
- **Honest UI**: candidates, not predictions. Confidence scores labelled provisional
  until backtested.

---

## 10. Open Items to Validate

1. ~~**Which FMP tier** bundles screener + all-shares-float + intraday extended-hours
   history + news.~~ **RESOLVED** — see `docs/PLAN.md`. Free serves EOD + float + quote +
   profile for 43 symbols; screener/stock-list/batch-quote need Starter; extended-hours
   intraday (`extended=true`) needs Premium.
2. **Premarket volume coverage**: does FMP's intraday data cover from 04:00 ET, or only
   from 08:00? This determines whether the full-early-session requirement is achievable
   as specified.
3. **Historical intraday depth**: needed both for the 20-session volume profile and for
   Phase 5 backtesting. Likely the biggest hidden cost in the project.
4. **Rate limits** on the chosen tier vs. worst-case Stage-2 candidate count.
5. **Short interest** availability and lag (FINRA reports ~2×/month — slow filter only).
6. **Auth**: dashboard is currently unauthenticated. Deferred by decision, but revisit
   before wider sharing.
