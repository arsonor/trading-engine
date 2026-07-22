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
   ├── Render Cron Job (pre-market scanner, 4:00–9:25 AM ET)
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

**Stage 2 — Momentum engine (every 5 min, 04:00 → 09:25 ET)**
- `3.0 <= gap_pct <= 15.0`
- `rvol_pct > 10.0`

**Stage 3 — Room-to-run (final confirmation, 09:25 ET)**
- `upside_pct >= 5.5` (5% target + 0.5% slippage/fee buffer)

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
> (Phase 5). The UI must never present the score as validated.

### 4.5 Timing model

Scans run **every 5 minutes from 04:00 to 09:25 ET**. Each run is **stateless**: it
recomputes accumulated premarket volume by summing intraday bars from 04:00 ET to now,
rather than carrying state between runs. The 09:25 run is the final confirmation pass and
is the one that applies Stage 3 and pushes the definitive alert set.

> **Render cron is UTC.** ET/DST conversion must be explicit in code. A UTC-pinned
> schedule silently drifts by one hour twice a year — for a market-timed scanner this is
> a correctness bug, not a cosmetic one. Schedule generously in UTC and gate the actual
> work on a computed ET timestamp.

---

## 5. Database Schema (v2)

**New tables**
1. `universe` — ticker, name, exchange, is_active, last_refreshed
2. `reference_data` — ticker (FK), static_float, volume_avg_20d, price_close_yesterday,
   high_yesterday, high_20d, sma_50, sma_200, computed_at
3. `premarket_volume_profile` — ticker (FK), bucket_minute (minutes from 04:00),
   avg_cumulative_volume, sessions_sampled, computed_at
4. `scan_runs` — id, started_at, finished_at, stage_counts_json, status, error
5. `alerts` — **extended**: ticker, gap_pct, rvol_pct, catalyst, confidence_score,
   entry_reference_price, nearest_resistance, upside_pct, suggested_entry_window,
   scan_run_id (FK), is_read, created_at

**Retained**: `rules` (now holds tunable scanner thresholds rather than per-tick
conditions), `watchlist` (demoted to an optional user favourites list).

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

# Scanner thresholds (tunable without redeploy)
SCAN_FLOAT_MAX=75000000
SCAN_AVG_VOLUME_MIN=500000
SCAN_GAP_MIN=3.0
SCAN_GAP_MAX=15.0
SCAN_RVOL_MIN=10.0
SCAN_UPSIDE_MIN=5.5
SCAN_PRICE_FLOOR=2.0

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
uv run python scripts/run_scan.py --dry-run --fixture # scanner against recorded fixtures
```

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
  04:00–09:25 window can be simulated. Never call `datetime.now()` directly in logic.
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

1. **Which FMP tier** bundles screener + all-shares-float + intraday extended-hours
   history + news. Confirm before committing to a plan.
2. **Premarket volume coverage**: does FMP's intraday data cover from 04:00 ET, or only
   from 08:00? This determines whether the full-early-session requirement is achievable
   as specified.
3. **Historical intraday depth**: needed both for the 20-session volume profile and for
   Phase 5 backtesting. Likely the biggest hidden cost in the project.
4. **Rate limits** on the chosen tier vs. worst-case Stage-2 candidate count.
5. **Short interest** availability and lag (FINRA reports ~2×/month — slow filter only).
6. **Auth**: dashboard is currently unauthenticated. Deferred by decision, but revisit
   before wider sharing.
