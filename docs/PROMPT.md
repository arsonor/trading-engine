# Claude Code Prompts — Trading Engine v2

Ready-to-use prompts, one per phase. **Run them in order, one per session.** Verify each
phase's "Definition of done" before starting the next.

Reference: `docs/CLAUDE.md` (spec) and `docs/PLAN.md` (roadmap).

**How to use:** open Claude Code in the repo root and paste the prompt block. Prompts
assume Claude Code can read `docs/CLAUDE.md` for full context — they intentionally don't
repeat the whole specification.

---

## Phase 0 — Infrastructure Migration

**Status:** ready
**Depends on:** nothing

````
# Phase 0 — Infrastructure Migration: Postgres everywhere + Render/Vercel/Supabase

## Context
Read `docs/CLAUDE.md` first for the full v2 specification.

This is `trading-engine`: a FastAPI + async SQLAlchemy backend (managed with `uv`,
Alembic migrations) and a React 19 / Vite / Zustand frontend. It currently uses SQLite
locally and deploys as a single Render blueprint (`render.yaml`).

We are repointing the infrastructure ahead of a major feature rebuild (a pre-market
universe scanner). This phase is INFRASTRUCTURE ONLY.

## Target architecture
- Local dev: PostgreSQL via the existing `docker-compose.dev.yml` (no more SQLite)
- Production database: Supabase PostgreSQL
- Production backend: Render (always-on web service + a separate Cron Job service)
- Production frontend: Vercel (static build)

## Scope

1. **Postgres for local development**
   - Verify/repair `docker-compose.dev.yml` so it starts Postgres 16 with sane defaults
     and a named volume for persistence.
   - Remove SQLite as a supported backend. `DATABASE_URL` must be a Postgres async DSN
     (`postgresql+asyncpg://...`). Fail fast with a clear error if it isn't.
   - Audit the codebase for SQLite-specific assumptions (column types, defaults, pragmas,
     connection args, Alembic `render_as_batch`) and convert to Postgres-native equivalents.

2. **Migrations**
   - Confirm every Alembic migration runs cleanly against an empty Postgres database.
   - Fix any migration that only worked under SQLite.
   - Verify `uv run alembic upgrade head` succeeds from scratch.

3. **Configuration**
   - Consolidate settings in `app/config.py` (pydantic-settings). Required env vars
     documented and validated at startup: DATABASE_URL, CORS origins, log level,
     environment name.
   - Add `FMP_API_KEY` and `FMP_BASE_URL` settings (unused this phase — wire the config only).
   - Add scanner threshold settings as documented in `docs/CLAUDE.md` section 6, with
     defaults. They are unused this phase but must be loadable.
   - Ensure CORS allows the Vercel frontend origin, configurable per environment.
   - Update `.env.example` to reflect exactly what's needed. `backend/.env` stays the
     backend's source of truth.

4. **Supabase compatibility**
   - Ensure the async engine works with Supabase's pooled connection (pgBouncer):
     appropriate pool settings, and disable prepared-statement caching where required by
     transaction-mode pooling.
   - Document in the README which Supabase connection string to use (pooled vs direct)
     for the app versus for migrations.

5. **Render + Vercel deployment config**
   - Rewrite `render.yaml` for: (a) one always-on web service for the API/WebSocket, and
     (b) one Cron Job service placeholder for the future pre-market scan. The cron
     entrypoint must be a stub that logs and exits 0 — no scanning logic yet.
   - Remove any Render-managed database from the blueprint; the database is Supabase now.
   - IMPORTANT: Render cron schedules are UTC. Add a clearly-commented placeholder
     schedule plus a README note on US Eastern time and DST handling.
   - Add Vercel config for the frontend build, with API base URL and WebSocket URL from
     environment variables. No hardcoded `onrender.com` URLs anywhere in frontend source.

6. **Health and verification**
   - `/health` reports app status plus database connectivity.
   - Update the README with an accurate "Getting started": start Postgres, run migrations,
     run backend, run frontend, smoke-test.

## Constraints
- Do NOT implement any scanner, FMP client, or scoring logic in this phase.
- Do NOT modify existing business/rule logic beyond what Postgres requires.
- Preserve the existing alert WebSocket broadcast mechanism and frontend behaviour.
- Do NOT restore or import `backup.sql` — it is stale legacy data.
- Keep changes reviewable; explain any non-obvious decision.

## Definition of done
From a clean checkout, this sequence works:
1. `docker compose -f docker-compose.dev.yml up -d`
2. `cd backend && uv sync && uv run alembic upgrade head`
3. `uv run uvicorn app.main:app --reload --port 8000` → `/health` healthy, DB OK
4. `cd frontend && npm install && npm run dev` → dashboard loads at localhost:5173
5. The existing seed/simulate smoke test still produces an alert visible in the dashboard
6. `render.yaml` and the Vercel config are valid, with no hardcoded secrets or URLs
7. Existing test suite passes

Report anything you find that would block the scanner work in later phases.
````

---

## Phase 1 — FMP Client & Reference-Data Pipeline

**Status:** blocked by Phase 0 + FMP capability validation
**Depends on:** Phase 0

> **Before running this prompt**, confirm with FMP's docs/support:
> 1. Does the purchased tier include intraday historical bars **with extended hours**?
> 2. Does premarket intraday data start at **04:00 ET** or only 08:00 ET?
> 3. How many days of intraday history are available (need ≥ 20 sessions; more for backtesting)?
> 4. Rate limits on the tier.
>
> If extended-hours intraday is unavailable or shallower than 20 sessions, **stop and
> renegotiate the RVOL definition** before building the profile job.

````
# Phase 1 — FMP client + nightly reference-data pipeline

## Context
Read `docs/CLAUDE.md` (sections 3, 4, 5) and `docs/PLAN.md` (Phase 1) first.

Phase 0 is complete: Postgres locally, Supabase in prod, Render web + cron stub, Vercel
frontend. Now build the data backbone the scanner depends on.

## Scope

1. **FMP API client** (`app/services/fmp_client.py`)
   - Async client with auth, timeouts, retries with exponential backoff, and
     rate-limit awareness (respect limits; never hammer).
   - Typed response models (pydantic). Endpoints needed: symbol/universe list,
     all-shares-float, historical daily bars, intraday bars (extended hours),
     real-time quote, stock screener.
   - Clear, typed errors distinguishing: rate-limited, not-found, auth failure,
     transient network, malformed payload.

2. **Fixture recorder** (test infrastructure — build this early)
   - A mode that records real FMP responses to `tests/fixtures/fmp/`.
   - A replay client used by tests. CI must NEVER hit the live FMP API.

3. **New tables + migrations** (per `docs/CLAUDE.md` section 5)
   - `universe`, `reference_data`, `premarket_volume_profile`, `scan_runs`.
   - Index `reference_data` to make the Stage-1 query fast
     (`static_float`, `volume_avg_20d`).

4. **Universe sync job**
   - Fetch tradable US equities (common stock; exclude ETFs/funds where identifiable)
     into `universe`. Mark delisted/missing tickers inactive rather than deleting.

5. **Reference data job**
   - For each active ticker compute and store: `static_float`, `volume_avg_20d`,
     `price_close_yesterday`, `high_yesterday`, `high_20d`, `sma_50`, `sma_200`.
   - Batch requests; cache aggressively; stay inside rate limits.

6. **Premarket volume profile job**
   - For each ticker, build cumulative premarket volume in 5-minute buckets from
     04:00 ET, averaged over the last 20 sessions → `premarket_volume_profile`.
   - Store `sessions_sampled` so downstream code knows the profile's reliability.
   - Skip/flag tickers with insufficient history rather than silently averaging noise.

7. **CLI entrypoint**
   - `scripts/refresh_reference_data.py` with `--universe-only`, `--reference-only`,
     `--profile-only`, `--tickers AAPL,MSFT`, `--dry-run`.
   - Idempotent and resumable: a partial failure must not corrupt existing rows.
   - Structured logging with progress, counts, and timing.

## Constraints
- Do NOT implement the scanner stages — Phase 2.
- Do NOT delete `alpaca_client.py` / `stream_manager.py` yet; leave them untouched as a
  working fallback until the scanner proves out.
- All jobs must run standalone from CLI (this is what the Render cron will invoke).
- Handle missing/null float gracefully — it will be absent for some tickers.
- Tests use recorded fixtures only.

## Definition of done
1. `uv run python scripts/refresh_reference_data.py --tickers AAPL,MSFT --dry-run` works
2. A full run populates all four tables without violating rate limits
3. Re-running is idempotent (no duplicates, no corruption)
4. The Stage-1 query (`float < 75M AND avg_volume_20d > 500K`) returns a sane candidate
   count in well under a second
5. Tests pass offline against fixtures
6. Report: actual universe size, Stage-1 survivor count, full-run wall time, API calls
   consumed, and how many tickers lacked float or sufficient intraday history
````

---

## Phase 2 — Scanner Pipeline

**Status:** blocked by Phase 1
**Depends on:** Phase 1

````
# Phase 2 — The 3-stage pre-market scanner

## Context
Read `docs/CLAUDE.md` section 4 (full scanner spec) and `docs/PLAN.md` (Phase 2) first.
Phase 1 is complete: `universe`, `reference_data`, and `premarket_volume_profile` are
populated, and the FMP client with fixture replay exists.

## Scope

1. **Scanner service** (`app/services/scanner/`)
   - Stage 1: SQL candidate query against `reference_data` (float, avg volume, price floor).
   - Stage 2: for each candidate compute `gap_pct` and time-of-day-normalized `rvol_pct`;
     apply 3.0 ≤ gap ≤ 15.0 and rvol > 10.0.
   - Stage 3: compute `nearest_resistance` (lowest of prior high / 20d high / SMA-50 /
     SMA-200 that is ABOVE current price) and `upside_pct`; require ≥ 5.5.
   - Risk filters: price floor, minimum dollar volume, market-wide tape check.
   - All thresholds read from config — never hardcoded.

2. **Time-of-day-normalized RVOL**
   - Accumulated premarket volume from 04:00 ET to now, divided by the expected
     cumulative volume for this ticker at this clock time (from
     `premarket_volume_profile`), × 100.
   - Define explicit fallback behaviour when a ticker has no/insufficient profile:
     skip it, or fall back to the simple full-day-average RVOL and FLAG the alert as
     using a degraded metric. Document whichever you choose.

3. **Clock and timezone handling — treat as correctness-critical**
   - Inject the current time; no direct `datetime.now()` inside scanner logic.
   - All market logic in `America/New_York`, converted explicitly. Render cron is UTC.
   - Schedule generously in UTC and gate real work on a computed ET timestamp, so DST
     transitions cannot shift the scan by an hour.
   - Tests must cover both DST transitions.

4. **Stateless scan runs**
   - Each run recomputes accumulated volume from 04:00 ET by summing intraday bars.
   - No state carried between cron invocations.

5. **Observability** (`scan_runs`)
   - Persist per run: start/end, per-stage survivor counts, API calls used, errors.
   - A failed or empty scan must be distinguishable from "no candidates today" — this
     is the single most important failure mode to make visible.

6. **CLI + cron entrypoint**
   - `scripts/run_scan.py` with `--dry-run`, `--fixture`, `--at "2026-07-20 08:45 ET"`,
     `--verbose`.
   - Wire this as the Render cron command (replacing the Phase 0 stub); every 5 minutes,
     04:00–09:25 ET.

7. **Tests**
   - Golden-case boundary tests: gap exactly 3.0 and 15.0, rvol exactly 10.0, upside
     exactly 5.5 — pin inclusive vs exclusive behaviour deliberately.
   - Full-pipeline fixture replay producing a deterministic candidate set.
   - Degraded-path tests: missing profile, missing float, stale reference data, FMP
     errors mid-scan.

## Constraints
- Alerts are NOT yet persisted or broadcast — Phase 3. Output to logs/stdout for now.
- No live API calls in tests.
- The scan must complete well inside 5 minutes for the real candidate count.
- If Stage 2 candidate volume risks breaching rate limits, batch and document the ceiling.

## Definition of done
1. `uv run python scripts/run_scan.py --fixture --at "..."` produces a deterministic set
2. All three stages have passing boundary tests
3. DST transition tests pass
4. `scan_runs` records a complete audit trail per run
5. A dry run against live FMP at an arbitrary time completes within rate limits, and you
   report: candidates per stage, wall time, and API calls consumed
````

---

## Phase 3 — Scoring, Alerts & Dashboard

**Status:** blocked by Phase 2
**Depends on:** Phase 2

````
# Phase 3 — Confidence scoring, alert delivery, dashboard rebuild

## Context
Read `docs/CLAUDE.md` sections 1, 4.4 and `docs/PLAN.md` (Phase 3) first.
Phase 2 is complete: the scanner produces qualified candidates.

## Scope

1. **Confidence score**
   - Transparent weighted formula over available signals (gap position within the
     3–15% band, rvol magnitude, upside headroom, liquidity, profile reliability).
   - Weights as named constants in config with a documented rationale.
   - Every score carries a breakdown of its contributing factors — the user must be able
     to see WHY, not just a number.
   - Mark the score PROVISIONAL in both API and UI until Phase 5 backtesting.

2. **Alert model + persistence**
   - Extend `alerts` to the v2 contract in `docs/CLAUDE.md` 4.4, with `scan_run_id` FK.
   - Alembic migration. Deduplicate: one alert per ticker per session, updated in place
     as later scans refine it, rather than spamming a new row every 5 minutes.
   - Broadcast via the existing client WebSocket channel.

3. **API + contract**
   - Endpoints to list/filter alerts for the current session, fetch a single alert with
     its score breakdown, and list recent scan runs.
   - Update `openapi/spec.yaml` and regenerate frontend TS types.

4. **Dashboard rebuild (mobile-first — a phone is the primary device)**
   - Alert card: ticker, gap%, RVOL, catalyst, confidence + breakdown, suggested entry
     window, entry reference price, resistance and upside.
   - Session view: today's candidates, sorted by confidence, updating live.
   - Scan-run status: last successful scan time, per-stage counts, and a clear failure
     state. "No candidates" must never look like "scanner broken", and vice versa.
   - Settings: edit scanner thresholds without a redeploy.
   - Retire or repurpose v1 pages that no longer apply (watchlist-era Rules page).

5. **Honest framing (non-negotiable)**
   - UI states plainly: these are CANDIDATES meeting structural criteria, not predictions.
   - Confidence is labelled provisional/unvalidated.
   - A visible "not financial advice / decision-support only" note.

## Constraints
- Do NOT add trade execution — ever.
- Preserve the existing WebSocket transport; extend the payload, don't replace the channel.
- Keep the frontend readable on a phone screen without horizontal scrolling.

## Definition of done
1. A fixture scan produces alerts persisted with full v2 fields and score breakdowns
2. Alerts appear live in the dashboard via WebSocket
3. Dashboard is usable on a 390px-wide viewport
4. Threshold changes in Settings take effect on the next scan without redeploy
5. Scan failure vs. zero candidates are visually distinct
6. OpenAPI spec and generated types are in sync; tests pass
````

---

## Phases 4–6

Not yet written as prompts — their design depends on what Phases 1–3 reveal (especially
FMP's real data depth). See `docs/PLAN.md` for scope:

- **Phase 4 — Enrichment:** catalyst/news, sector relative strength, bid-ask spread,
  short interest, halt risk, gap-and-go history.
- **Phase 5 — Backtesting & calibration:** replace guessed confidence weights with
  fitted ones. The spec explicitly requires this before the score can be trusted.
- **Phase 6 — Hardening:** authentication, push notifications, cost/rate monitoring,
  scan-failure alerting, MCP server decision.

Write the Phase 4 prompt only after Phase 3 ships and the FMP data depth question
(open item #3 in `docs/CLAUDE.md`) is settled.

---

## Working Notes

- **One phase per session.** Long multi-phase sessions lose context and produce
  half-migrated code.
- **Verify "Definition of done" before advancing.** Each phase assumes the previous one
  actually works, not that it was merely attempted.
- **Never let CI touch the live FMP API.** Fixtures always — cost and flakiness both.
- **`backup.sql` is stale.** Legacy alerts reference dead rule IDs. Don't restore it.
- **Alpaca credentials still exist** in `.env`. Leave the v1 path working as a fallback
  smoke test until the scanner is proven, then remove it deliberately in its own commit.
