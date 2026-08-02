# Claude Code Prompts — Trading Engine v2 (tier-staged delivery)

Run in order, one per session. Verify each phase's Definition of done before advancing.
Reference: `docs/CLAUDE.md` (spec), `docs/PLAN.md` (roadmap + version ladder),
`docs/PROJECT_REPORT.md` (V1→V4 tiers).

- **Phase 0 — Infrastructure: ✅ DONE** (Postgres everywhere, Render Frankfurt web +
  cron stub, Vercel, Supabase, CI trimmed, connectivity verified). Prompt removed;
  see git history if needed.
- Phases 1–3 build **app V1 on the free FMP tier** — no subscription required.
- Phase 4+ (V2, Starter tier) prompts get written once V1 ships. The two former FMP
  open questions are **answered** (FMP support, July 2026): Starter intraday bars are
  regular-hours only; `extended=true` (pre/after-market bars) requires Premium.
  → Accurate RVOL + volume profiles are V3; V2 uses a flagged approximation.

---

## Phase 1 (V1) — FMP client, API budget guard, reference-data pipeline

**Status:** ✅ DONE (25 July 2026)
**Tier:** FMP Basic (free) — 250 calls/day hard cap, EOD data only, 43 accessible symbols

> **What the live free tier actually does** — measured, and it changed the design:
> `batch-quote`, `stock-list` and `company-screener` are all **402 Restricted Endpoint**,
> so the symbol probe falls back to one `quote` call per symbol. Restricted *symbols* also
> return **402**, with a **plain-text** body, and both restriction messages contain
> "not available under your current subscription" — only `"Restricted Endpoint:"` vs
> `"Premium Query Parameter: 'Special Endpoint"` separates "fail the path" from "skip the
> ticker". Full table in `docs/PLAN.md`.
>
> Delivered: `app/services/fmp/` (client, budget guard, fixtures, typed errors),
> `app/services/reference/` (metrics, pipeline, probe), `app/services/scanner/rvol.py`,
> five new tables, and CLIs `probe_fmp_symbols.py` / `refresh_reference_data.py` /
> `fmp_budget.py` / `record_fmp_fixtures.py`. Prompt kept below for reference.

````
# Phase 1 — FMP client + daily budget guard + nightly reference pipeline (free tier)

## Context
Read `docs/CLAUDE.md` (sections 3–5) and `docs/PLAN.md` first. Phase 0 is complete:
Postgres locally (docker, port 5433), Supabase in prod, Render web + cron stub, Vercel
frontend, `FMP_API_KEY` already wired into config.

We are building app V1 against FMP's FREE tier. Hard constraints that must shape the
design (do not treat these as soft limits):
- 250 API calls per DAY, hard stop with HTTP 429. No overages.
- End-of-day data only. No intraday endpoints, no real-time guarantees.
- Most endpoints only serve a fixed sample of ~87 large-cap symbols (AAPL, TSLA, ...).
- 500 MB bandwidth / 30 days.

## FMP API facts (from official docs — use these, do not invent endpoints)
- Base: `https://financialmodelingprep.com/stable/<endpoint>`
- Auth: `?apikey=KEY` query param (or `apikey` header)
- Endpoints for this phase:
  - `historical-price-eod/full?symbol=AAPL` → full daily history: date, open, high,
    low, close, volume, vwap, change. ONE call yields everything needed to compute
    volume_avg_20d, high_20d, sma_50, sma_200, prior close/high locally.
  - `shares-float?symbol=AAPL` → float shares, free float, outstanding shares
  - `quote?symbol=AAPL` and `batch-quote?symbols=AAPL,MSFT` → quote snapshot
  - `profile?symbol=AAPL` → company name, exchange, sector, market cap
  - `stock-list`, `company-screener` → directory/screener (may be restricted on free;
    probe, don't assume)
- Efficient pattern: **2 calls per ticker per day** (eod/full + shares-float).
  Budget 250/day → a universe of ~80–100 tickers with headroom for probes and retries.

## Scope

1. **FMP client** (`app/services/fmp/client.py`)
   - Async httpx client; auth via query param from settings; sane timeouts.
   - Retries with exponential backoff for transient errors ONLY (5xx, network).
     NEVER retry a 429 — a daily-cap 429 means stop, not try harder.
   - Typed pydantic response models for each endpoint used.
   - Typed errors: BudgetExhausted, RateLimited, SymbolNotAvailable, AuthFailed,
     TransientError, MalformedResponse.

2. **Daily API budget guard** — build this FIRST; every FMP call goes through it
   - `api_budget` table: date (UTC), calls_used, updated_at.
   - Atomic increment per call; configurable ceiling `FMP_DAILY_BUDGET` (default 230,
     deliberately below 250 to leave manual-testing headroom).
   - When exhausted: raise BudgetExhausted with a clear message including reset time.
     Jobs must fail gracefully and record partial progress — never corrupt tables.
   - CLI: `scripts/fmp_budget.py` showing today's usage.

3. **Symbol probe** (`scripts/probe_fmp_symbols.py`)
   - The free tier's accessible-symbol sample must be discovered, not assumed.
   - Probe a candidate list (S&P-100-style megacaps + a handful of known small caps to
     confirm they are NOT accessible) using batch-quote where possible to conserve budget.
   - Persist results into `universe` with an `is_accessible_free_tier` flag.
   - Report: how many symbols are usable; this set IS the V1 universe.

4. **Database migrations** (Alembic, per `docs/CLAUDE.md` section 5)
   - Tables: `universe`, `reference_data`, `scan_runs`, `api_budget`, and
     `premarket_volume_profile` (schema only — populated in V3, since building profiles
     requires `extended=true` pre-market bars, Premium-only per FMP support)
   - Indexes on `reference_data(static_float, volume_avg_20d)` for the Stage-1 query.

5. **Fixture recorder + replay** (`tests/fixtures/fmp/`)
   - Recorder mode captures real responses to JSON on disk (one recording session,
     budget-aware). Replay client serves them in tests. CI NEVER hits live FMP.
   - Record at minimum: eod/full and shares-float for 5 accessible symbols, plus one
     not-available symbol and one malformed/empty case.

6. **Reference-data pipeline** (`scripts/refresh_reference_data.py`)
   - For each active universe ticker: fetch eod/full + shares-float (2 calls), compute
     locally: volume_avg_20d, price_close_yesterday, high_yesterday, high_20d, sma_50,
     sma_200; upsert into `reference_data` with computed_at.
   - Budget-aware: checks remaining budget BEFORE starting each ticker; stops cleanly
     and reports progress when close to the ceiling.
   - Idempotent and resumable: re-running continues where it stopped (skip tickers
     already refreshed today unless `--force`).
   - Flags: `--tickers AAPL,MSFT`, `--dry-run`, `--force`, `--limit N`.
   - Structured logging: per-ticker result, calls used, wall time.

7. **RVOL interface** (`app/services/scanner/rvol.py`)
   - `RvolCalculator` protocol with two implementations:
     - `SimpleRvol`: premarket_volume / volume_avg_20d (usable from V2)
     - `NormalizedRvol`: time-of-day profile version — in V1 this raises
       FeatureRequiresIntraday with a message stating it needs `extended=true`
       pre-market bars, available from FMP Premium (app V3).
   - Selected via config `RVOL_MODE=simple|normalized`. This seam is the whole point:
     upgrading tiers later must be a config change, not a rewrite.

## Constraints
- Do NOT implement the scanner stages (Phase 2) or touch the dashboard (Phase 3).
- Do NOT delete Alpaca code yet.
- Every FMP-touching test uses fixtures. The recorder is the only live-API test path,
  run manually.
- Handle missing float gracefully (null-tolerant), and record which symbols lack it.
- All new settings go through `app/config.py` with documented defaults, and
  `.env.example` updated.

## Definition of done
1. `uv run python scripts/probe_fmp_symbols.py` reports the accessible universe and
   persists it (share the count and a sample in your final report)
2. `uv run python scripts/refresh_reference_data.py --tickers AAPL,MSFT --dry-run` works
3. A real limited run (e.g. `--limit 10`) populates `reference_data` correctly and
   `scripts/fmp_budget.py` shows the expected call count (~2/ticker + probes)
4. Re-running the same day consumes ~0 additional calls (idempotence)
5. Exhausting the budget artificially (set ceiling to 3) fails cleanly with partial
   progress preserved
6. All tests pass offline against fixtures; ruff clean
7. Final report: accessible-symbol count, calls consumed, any endpoint that behaved
   differently from the docs (screener/stock-list especially), and anything that
   blocks Phase 2
````

---

## Phase 2 (V1) — Scanner pipeline (three stages + threshold profiles)

**Status:** ✅ DONE (27 July 2026)

> Delivered: `app/services/scanner/` — `clock.py` (injectable clock, ET/DST),
> `profiles.py` (production/demo), `snapshot.py` (`MarketSnapshot` + fixture provider +
> documented V2 live stub), `stages.py`, `risk.py`, `pipeline.py` (+ `scan_runs`), plus
> `scripts/run_scan.py` and two committed snapshot scenarios.
>
> Funnel on real free-tier reference data: **demo** 10 → 10 → 6 → 3 candidates
> (ADBE/BA/C); **production** 10 → 0, correctly reported as a successful scan of a quiet
> market rather than a failure. Boundary conventions are pinned in
> `tests/unit/test_scanner_stages.py`; percentages compare at 6dp so the displayed number
> and the pass/fail decision always agree.

````
# Phase 2 — 3-stage scanner on free-tier data + fixtures

## Context
Read `docs/CLAUDE.md` section 4 (full scanner spec) and `docs/PLAN.md`. Phase 1 is done:
FMP client + budget guard, populated `universe` and `reference_data`, fixture replay,
pluggable RVOL (simple/normalized stub).

V1 data reality: EOD only, mega-cap universe. Stage 1 and Stage 3 run on REAL data.
Stage 2 (live gap + premarket RVOL) is implemented COMPLETELY but fed by fixtures /
synthetic inputs until V2 provides real-time + intraday data.

## Scope

1. **Scanner service** (`app/services/scanner/`)
   - Stage 1: SQL candidate query on `reference_data` (float, avg volume, price floor).
   - Stage 2: gap_pct (3.0–15.0) + RVOL (>10%) via the RvolCalculator interface. Input
     is a `MarketSnapshot` abstraction (price + accumulated volume per ticker) with two
     providers: `FixtureSnapshotProvider` (V1) and a documented interface a future
     `FmpLiveSnapshotProvider` (V2) will implement.
   - Stage 3: nearest_resistance = lowest of {high_yesterday, high_20d, sma_50, sma_200}
     ABOVE current price; upside_pct >= 5.5.
   - Risk filters: price floor, min dollar volume, market-tape check (stub returning
     neutral in V1, interface ready for V2).

2. **Threshold profiles** — critical for V1 demos
   - `production`: the real spec (float < 75M, etc.).
   - `demo`: loosened float cap (e.g. < 20B) so free-tier mega-caps can pass Stage 1
     and the pipeline visibly fires end-to-end with real reference data.
   - Profile selected per run; the profile name is stamped into `scan_runs` and onto
     every alert payload it produces. Demo output must never be mistakable for real.

3. **Clock + timezone (correctness-critical)**
   - Injectable clock; zero direct `datetime.now()` in scanner logic.
   - All market logic in America/New_York; explicit conversion; DST transition tests
     both directions.

4. **Observability** (`scan_runs`)
   - started/finished, profile, per-stage survivor counts, API calls used, errors.
   - "Failed scan" must be distinguishable from "zero candidates".

5. **CLI** `scripts/run_scan.py`
   - `--fixture`, `--profile demo|production`, `--at "2026-07-28 08:45 ET"`, `--dry-run`,
     `--verbose`. Output to stdout/logs only — alert persistence is Phase 3.

6. **Tests**
   - Golden-case boundary tests: gap 3.0/15.0, rvol 10.0, upside 5.5 — pin
     inclusive/exclusive deliberately and document the choice.
   - Full-pipeline fixture run → deterministic candidate set.
   - Degraded paths: missing float, missing profile data, budget exhausted mid-scan.
   - DST tests.

## Constraints
- No alert persistence/broadcast yet (Phase 3). No dashboard changes.
- No live FMP calls in tests; a manual `--dry-run` against live data is the only
  live path, and it must respect the budget guard.

## Definition of done
1. Fixture run at a fixed `--at` produces a deterministic, documented candidate set
2. Demo-profile run against REAL reference data completes and (given loosened
   thresholds + fixture snapshots) produces at least one Stage-3 survivor
3. Boundary + DST + degraded-path tests pass; ruff clean
4. `scan_runs` shows a complete audit trail including profile name
5. Report: survivor counts per stage in both profiles, and anything blocking Phase 3
````

---

## Phase 3 (V1) — Scoring, alerts & dashboard

**Status:** ✅ DONE (28 July 2026) — **this completes app V1.**

> Delivered: `app/services/scanner/scoring.py` (5-factor provisional score with a
> null-safe upside fallback), `app/services/scanner/settings_store.py` (redeploy-free
> threshold edits), `app/services/alerts/` (dedup + broadcast), `app/api/v1/scanner.py`
> (7 endpoints), the extended `alerts` table + `scanner_settings`, and a rebuilt
> mobile-first dashboard (`Candidates` / `Scans` / `Settings`). Watchlist-era pages are
> retired; the `/rules` API stays until Alpaca is removed.
>
> Verified in a browser: demo scan → 3 candidates with breakdowns, live over WebSocket
> with no reload; a forced failure renders as a red "SCANNER FAILING" panel that is
> visually unmistakable from the grey "quiet market" state; no horizontal scroll at 390px.
> 618 backend + 74 frontend tests green.

````
# Phase 3 — Confidence scoring, alert delivery, dashboard rebuild (V1)

## Context
Read `docs/CLAUDE.md` sections 1, 4.4, and `docs/PLAN.md`. Phases 1–2 are done: the
scanner produces qualified candidates (real Stage 1/3 data; fixture-fed Stage 2;
demo/production profiles).

## Scope

1. **Confidence score**
   - Transparent weighted formula (gap position in band, rvol magnitude, upside
     headroom, liquidity, data-quality/profile reliability). Weights as named config
     constants with rationale comments.
   - Every score carries a factor breakdown. API + UI label it PROVISIONAL
     (unvalidated until V3 backtesting).
   - **`upside_pct` and `nearest_resistance` MUST be treated as nullable throughout.**
     Today every candidate reaching this point has a float upside, because Stage 3
     rejects tickers trading above all four resistance levels. That rejection is a
     deferred strategy decision (see `docs/CLAUDE.md` 4.3 "Breakout convention" and open
     question #8) that may be reversed after live V2 use. If scoring, the schema, or the
     UI assume a non-null upside, reversing it later becomes a cross-cutting refactor
     instead of a one-branch change. So: score must degrade gracefully with a null upside
     (documented fallback weight), the API schema must mark the field optional, and the
     alert card must render a sensible "no overhead resistance" state.

2. **Alert model + persistence**
   - Extend `alerts` to the v2 contract (`docs/CLAUDE.md` 4.4) + `scan_run_id` FK +
     `profile` field. Alembic migration.
   - Dedup: one alert per ticker per session, updated in place by later scans.
   - Broadcast over the existing WebSocket channel.

3. **API + contract**
   - Endpoints: list/filter session alerts; single alert with score breakdown; recent
     scan runs. Update `openapi/spec.yaml`; regenerate TS types.

4. **Dashboard rebuild (mobile-first — phone is the primary device)**
   - Alert card: ticker, gap%, RVOL, catalyst (nullable), confidence + breakdown,
     entry window, entry price, resistance, upside. Demo-profile alerts visibly badged.
   - Session view sorted by confidence, live-updating.
   - Scan-status panel: last successful scan, per-stage counts, explicit failure state.
     "No candidates" and "scanner broken" must look DIFFERENT.
   - Settings: edit thresholds + profile without redeploy.
   - Retire/repurpose watchlist-era pages that no longer apply.
   - Honest framing: candidates not predictions; not financial advice; provisional score.

5. **Cleanup**
   - Wire the Render cron stub to `run_scan.py --profile production` (it will produce
     zero candidates on free tier — that is correct and must display as such).

## Constraints
- No trade execution, ever. Preserve the WebSocket transport (extend payloads only).
- Readable on a 390px viewport without horizontal scroll.

## Definition of done
1. Fixture scan persists alerts with full v2 fields + breakdowns; they appear live in
   the dashboard
2. Demo vs production profiles visually distinct end-to-end
3. Threshold/profile changes in Settings take effect next scan without redeploy
4. Scan failure vs zero candidates are distinct in the UI
5. OpenAPI + TS types in sync; tests pass; usable on a phone
6. This completes app V1 — report anything to verify before the Starter subscription
   (feeds the two open FMP questions in PLAN.md)
````

---

## Phase 3.5 (V1 cleanup) — Remove Alpaca and the v1 schema vestiges

**Status:** ✅ DONE (29 July 2026) — delivered as three commits: MCP removal,
Alpaca removal, schema migration.
**Depends on:** Phase 3 (V1 shipped)
**Why now:** this is DDL on a populated table. Today it holds a handful of rows and has
zero users; from V2 onward the end user checks the dashboard every morning and every
migration carries a real rollback cost. The round-trip migration test infrastructure is
also freshly built and in CI. Doing this before Phase 4 means the live FMP work starts
on an unambiguous schema.

````
# Phase 3.5 — Remove Alpaca + v1 schema vestiges

## Context
Read `docs/CLAUDE.md` and `docs/PLAN.md` first. App V1 has shipped: FMP client, budget
guard, 3-stage scanner, confidence scoring, alerts and dashboard all work. The v1 Alpaca
watchlist/rule-engine path is now dead weight — the deployed dashboard reports
`Alpaca API — Disconnected`, and the real smoke tests are `seed_test_alerts.py` and the
fixture-driven scan.

This phase removes v1. It is deliberately sequenced BEFORE the V2 (FMP Starter) work so
the schema is clean when the live snapshot provider is written, and because a schema
migration is cheapest now while nobody depends on the app.

## Scope — tier 1: dead code and credentials (low risk)

1. Delete `app/services/alpaca_client.py` and `app/services/stream_manager.py`, plus any
   module existing solely to support them.
2. Remove Alpaca settings from `app/config.py` and `.env.example`, and the Alpaca env
   vars from `render.yaml` (both the web service and the cron job).
3. Delete tests that only exercise the Alpaca client / stream manager. Do NOT delete
   tests that touch alerts — those are covered in tier 2.
4. Audit the MCP server (`app/mcp/`, `run_mcp.py`) for Alpaca-dependent tools and remove
   them. Report what remains and whether the MCP server still has a coherent purpose in
   v2 — do not delete the whole server without flagging it first.
5. Remove Alpaca references from the README and any docs describing it as a live
   fallback.

## Scope — tier 2: schema cleanup (needs the round-trip test)

6. **Drop the retained v1 columns from `alerts`**: `rule_id`, `setup_type`,
   `entry_price`, `stop_loss`, `target_price`, `market_data_json`, plus the FK to
   `rules`.

7. **Rename `alerts.symbol` → `alerts.ticker`** and delete the storage/API mapping layer
   in `app/schemas/scanner.py`. Dependents that must move with it: the index on `symbol`
   and the `uq_alerts_symbol_session` unique constraint (rename to match).

8. **Decide the fate of the `rules` table — do not assume.**
   `docs/CLAUDE.md` §5 says `rules` would hold tunable scanner thresholds, but Phase 3
   created `scanner_settings` for exactly that, leaving `rules` orphaned. Establish
   whether anything still reads or writes it, then either drop it (with its model,
   repository, schemas, API routes and the retired YAML rule-engine code) or state
   clearly what it is still for. Either way, justify the choice and update
   `docs/CLAUDE.md` §5 to match reality.

9. **Decide and document what happens to existing v1-origin alert rows** (those with
   `session_date IS NULL`). Options: delete them, or keep them with null v2 fields.
   They are seeded test data locally, but the deployed database may hold others. The
   choice must be explicit in the migration docstring — not an accident of whichever DDL
   you happen to write.

10. **The migration must be reversible**, with the same discipline as the last hotfix:
    the downgrade restores the v1 columns as NULLABLE (v2 rows have no honest values for
    them), and the docstring states plainly that dropped v1 column data is not
    recoverable by re-upgrading.

## Constraints
- **No behavioural change to the v2 scanner.** Stages, scoring, thresholds, alert
  contract and dashboard behaviour must be identical before and after.
- The round-trip migration test must cover this migration **with realistic data
  present** — both v1-origin and v2-origin alert rows. An empty-database round trip
  proves nothing; that is precisely how the last downgrade bug shipped.
- Do NOT run anything against the production Supabase instance.
- The API contract stays as specified in `docs/CLAUDE.md` §4.4 — the field is already
  exposed as `ticker`, so this rename must be invisible to the frontend.
- Tier 1 and tier 2 may be separate commits if that eases review; they have very
  different risk profiles.

## Definition of done
1. No Alpaca code, settings, env vars, credentials or documentation references remain
   anywhere in the repo
2. `alerts` has no v1 columns; the storage column is `ticker`; the mapping layer is gone
3. The `rules` decision is made, implemented, justified, and `docs/CLAUDE.md` §5 updated
4. Round-trip test passes on a database seeded with BOTH v1-origin and v2-origin rows
5. Downgrade succeeds on that same populated database, and the data-loss note is in the
   migration docstring
6. The v2 scanner produces identical results before and after: run
   `scripts/run_scan.py --fixture --profile demo --at "<fixed time>"` on both sides and
   compare
7. Dashboard still works end to end (candidates, scan status, settings, demo badging)
8. Tests pass; ruff and eslint clean
9. Report: what the MCP audit found, what you decided about `rules` and why, and how
   many v1-origin alert rows the migration affects
````

---

## Phase 4-prep (free tier) — Enforce Row-Level Security on every table

**Status:** ✅ DONE (2 August 2026) — migration `dbdf5784db31` enables RLS on all eight
`public` tables with zero policies; `tests/integration/test_rls.py` fails (never skips)
when any `public` table lacks it. Policy lives in `app/core/rls.py`; the convention is
documented in `alembic/script.py.mako` and `alembic/README`, where the next migration
author will actually meet it.
**Depends on:** Phase 3.5
**Tier:** free — no subscription needed. Good use of the wait on FMP support.

````
# Phase 4-prep — Make missing RLS impossible to ship

## Context
Supabase flagged a CRITICAL security issue on this project: tables in the `public`
schema without Row-Level Security. Without RLS, anyone holding the project URL and the
(publicly-designed) anon key can read, edit and delete those tables through Supabase's
auto-generated Data API — bypassing the FastAPI backend entirely.

This has been fixed BY HAND on the production database with `ALTER TABLE ... ENABLE ROW
LEVEL SECURITY` for the current tables. That fix is not durable: every table a future
migration creates will lack RLS, and V2/V3 add several. `docs/PLAN.md` carries a
checklist reminder, but a reminder is not enforcement — it depends on a human reading
the plan at the right moment.

This phase converts "remember to enable RLS" into "CI fails if you didn't", the same way
the migration round-trip test converted "remember to test downgrades".

## Why RLS with NO policies is the correct configuration here
This project never uses the Supabase Data API. The backend connects directly over
Postgres as `postgres`, which owns the tables and carries BYPASSRLS — so RLS with zero
policies denies the Data API's `anon`/`authenticated` roles while leaving the
application completely unaffected. Do not write permissive policies to "make it work";
nothing needs to work through that path.

## Scope

1. **A migration that enables RLS on every existing table**
   - Enable RLS on all current `public` tables so local, CI and production match.
     Environment parity is a standing principle in this project — the production
     database must not be the only place RLS is on.
   - Handle `alembic_version` deliberately: decide whether it is in scope, and if it is
     excluded, say why in the migration docstring rather than leaving it an oversight.
   - Reversible downgrade (disable RLS), with the security implication noted in the
     docstring.

2. **A reusable convention for future migrations**
   - A small helper (e.g. `enable_rls(table_name)`) in a shared migration utility module,
     so new migrations enable RLS in one obvious line.
   - Document the convention where a developer will actually meet it: the Alembic README
     or a comment in `alembic/script.py.mako` so it appears in every generated migration
     stub.

3. **The enforcement test — this is the real deliverable**
   - Against a migrated Postgres database, query the catalog for every base table in
     `public` and assert each has `relrowsecurity = true`.
   - The failure message must name the offending tables and give the exact SQL to fix
     them — a developer hitting this in CI should not have to research anything.
   - Any deliberate exclusion lives in an explicit, commented allowlist in the test, so
     skipping a table is a visible decision rather than a silent gap.
   - This must run in CI (Postgres is already a CI service as of the last hotfix) and
     must FAIL rather than SKIP when the database is unavailable in CI — a silently
     skipped security test is worse than no test.

4. **Prove the test has force**
   - Temporarily add a table without RLS (or disable it on one), confirm the test fails
     with the intended message, then revert. Report the observed failure output.
   - This is the same verification discipline used on the downgrade round-trip test. A
     test nobody has watched fail is just a test that passes.

## Constraints
- Do NOT use `FORCE ROW LEVEL SECURITY`. That subjects the table owner to RLS too, which
  would break the application's own access.
- Do NOT create any RLS policies. Zero policies is the intended deny-all posture.
- No change to application behaviour, queries, or the alert contract.
- Do NOT run anything against the production Supabase instance — it has already been
  fixed by hand; the migration must be safe to re-apply there (idempotent).
- Document the assumption that the application's database role owns its tables or has
  BYPASSRLS. If a future deployment connects as a restricted role, RLS becomes
  load-bearing and policies would be required — note this so it is not discovered the
  hard way.

## Definition of done
1. Migration enables RLS on all existing tables and is idempotent (safe on a database
   where RLS is already on — i.e. production)
2. The helper + convention exist and are documented where a developer will see them
3. The enforcement test passes after the migration
4. The test demonstrably fails when a table lacks RLS — report the actual output
5. The test runs in CI and fails (not skips) if Postgres is unavailable there
6. App works unchanged locally: `/health`, `/api/v1/scanner/status`,
   `/api/v1/scanner/alerts` all behave as before
7. Migration round-trip test still passes on populated data
8. Tests pass; ruff clean
````

---

## Phase 4-prep (b) — Cleanups from the V1 production shakedown

**Status:** ✅ DONE (2 August 2026) — all three fixed. Issue 3 was resolved by scoping
`overrides_json` per profile (migration `9c3b774f629a`) rather than by clearing overrides
on profile switch, so the two profiles' tuning no longer collide; the pipeline now names
the demo/zero-Stage-1 misconfiguration instead of reporting it as a quiet market.
**Depends on:** Phase 3.5
**Tier:** free — no subscription needed
**Origin:** found while running V1 against Supabase for the first time. All three are
"the system reports something false while behaving correctly", which is the most
expensive kind of small bug — it sends you debugging the wrong thing.

````
# Phase 4-prep (b) — Three cleanups from the first production run

## Context
Read `docs/CLAUDE.md` and `docs/PLAN.md` first. V1 is complete and was run against the
production Supabase database for the first time. Three issues surfaced. None breaks the
scanner; two actively mislead the operator.

## Issue 1 — CLI scripts never dispose the database engine

`app/core/database.py` provides `close_db()` (which calls `await engine.dispose()`), but
no CLI script in `backend/scripts/` calls it. Connections are torn down by garbage
collection after the event loop has already closed.

Against local Docker Postgres this is invisible. Against Supabase (TLS) it produces a
noisy `Fatal error on SSL transport` / `RuntimeError: Event loop is closed` traceback on
every run, because the SSL transport's finaliser tries to write a close-notify to a dead
loop. It is cosmetic — the work has already committed — but it trains the operator to
ignore tracebacks, which is a bad habit to build into a tool that must be trusted when it
reports failure.

**Fix:** every CLI script disposes the engine inside the async context, in a `finally`
so it runs on the error path too. Cover all of `backend/scripts/`. The point is
deterministic cleanup of pooled connections; silencing the Windows traceback is a
side effect, not the goal — do not "fix" this by suppressing warnings.

## Issue 2 — The demo banner reports nominal thresholds, not effective ones

Observed output, from a single run:

    Thresholds : float < 75,000,000            <- effective (correct)
    WARNING ... float cap loosened to 20,000,000,000   <- nominal (wrong)
    Stage 1: 0/43 tickers passed (float < 75,000,000)  <- effective (correct)

The warning text comes from the profile's stored `description` string, which hardcodes
the designed value. After `resolve_profile()` applies stored overrides via
`replace(profile, **applied)`, that description is stale — it describes a profile that is
no longer in effect.

**Fix:** derive every human-readable threshold summary from the profile's actual field
values at render time. A hardcoded description that duplicates configuration is a second
source of truth and will go stale again. Prefer removing the parallel string over
remembering to update it.

## Issue 3 — Stored settings silently defeat the demo profile

The demo profile exists for exactly one reason: loosen the float cap so free-tier
mega-caps can reach Stage 1 and the pipeline can be seen working. But
`ScannerSettingsStore.resolve_profile()` applies the single stored settings row on top of
*any* profile. A user who saves thresholds while thinking in production terms silently
reverts demo's loosened cap — and the result presents as "0 candidates, successful scan,
quiet market", which is exactly the failure mode the whole scan-status design exists to
prevent.

**Decide the fix; do not assume.** Options, with the trade-off stated in the commit:
- **Scope settings per profile** (a row per profile). Structurally correct — demo and
  production are different regimes and should not share an override set. Costs a
  migration, which is cheap now that round-trip tests exist.
- **Protect the demo profile's loosened fields** from override.
- **Detect and warn loudly** when an override materially conflicts with the active
  profile's purpose.

Whichever is chosen, this must hold: **a demo scan whose loosened thresholds have been
reverted must never present as a quiet market.**

Additionally, add a sanity check to the scan output: **in the demo profile, Stage 1
passing 0 of N is almost certainly a misconfiguration, not a quiet market** — demo is
designed so the free-tier universe passes. Say so explicitly in that case, and point at
the effective thresholds.

## Constraints
- No change to scanner logic, stage arithmetic, thresholds, or the alert contract.
- Do NOT run anything against the production Supabase instance.
- If Issue 3 needs a migration, it is reversible and covered by the round-trip test on
  populated data, per the standing rule in `docs/PLAN.md`.
- Preserve the existing three-layer precedence documented in `settings_store.py`
  (env defaults → stored row → explicit per-run argument) unless the chosen fix
  deliberately changes it — in which case update that module docstring to match.

## Definition of done
1. Every script in `backend/scripts/` disposes the engine, including on the error path;
   no SSL/event-loop traceback when run against a TLS Postgres
2. Threshold summaries (banner, header, stage logs) all show identical effective values,
   pinned by a test that applies an override and asserts the banner reflects it
3. Issue 3's fix implemented, justified in the commit, with a test proving a stored
   override can no longer silently defeat the demo profile
4. Demo profile + 0 Stage-1 survivors produces an explicit misconfiguration warning, not
   a quiet-market message — with a test
5. `settings_store.py` docstring matches actual behaviour
6. Existing tests pass; ruff clean; scanner output otherwise byte-identical (verify with
   a fixture run before and after)
````

---

## Phase 4A (V2) — Starter capability probe

**Status:** ready — run on the first day of the Starter subscription, before any V2 design
**Depends on:** Phase 3.5, Phase 4-prep, an active FMP **Starter** key
**Why first:** Phase 1's probe immediately disproved three documented free-tier behaviours
(`batch-quote`, `stock-list` and `company-screener` were all 402). FMP support has now
answered what it can, but three things remain undocumented and one of them
(does the "aftermarket" quote work during **pre**-market?) determines whether V2 works at
all. Measure before building.

````
# Phase 4A — Empirically characterise the FMP Starter tier

## Context
Read `docs/PLAN.md` ("FMP Starter capabilities" + "call-budget arithmetic") first.

The key has been upgraded from Basic to **Starter**. FMP support confirmed: the
aftermarket quote endpoint returns volume; `batch-quote` is Premium-only (so every live
quote costs 1 call); `company-screener` cannot return float, only `shares-float` /
`shares-float-all` can.

This phase writes NO product code. It measures what the tier actually does, so 4B and 4C
are designed against reality rather than documentation. Deliverable = a probe script + a
written findings report.

## Questions to answer empirically

**A. Pre-market data — the critical unknown**

FMP support has confirmed: *Aftermarket **Quote*** is **post-close only** and does not
cover pre-market; there is **no dedicated pre-market quote endpoint**; and
`extended=true` (the pre-market bars path) is Premium-only. Their recommendation for
real-time pre-market activity is the **Aftermarket Trade** endpoint.

So `gap_pct` is probably fine but `rvol_pct` is in doubt. A *trade* payload is usually
last price + last trade **size** + timestamp — one transaction, not cumulative session
volume. Establish exactly what is available:

1. **`aftermarket-trade` during pre-market (04:00–09:30 ET)**: does it return data at all?
   Capture the full raw payload for several tickers. Enumerate every field.
2. **Does anything in that payload represent cumulative session volume**, as opposed to
   the size of a single trade? Distinguish them by *sampling the same ticker every ~2
   minutes for 30–60 minutes of a live pre-market session*: a cumulative field rises
   monotonically, a per-trade size fluctuates. **Record the raw series in the report** —
   this is the single most consequential measurement in the phase.
3. **The regular `quote` endpoint during pre-market.** FMP says Quote is "regular hours
   only", but day-cumulative `volume` fields often begin accumulating before the open even
   when `price` is stale. Sample it through the same window and report, per field, whether
   it updates pre-open: `price`, `volume`, `avgVolume`, `previousClose`, `dayHigh/Low`.
   **If `volume` accumulates pre-market, RVOL is saved** — this is the highest-value
   long-shot in the probe.
4. **The `company-screener` `volume` field during pre-market.** Same question, and if it
   works it is far better than either of the above: the screener returns many symbols per
   call, which would solve the volume problem *and* the missing-`batch-quote` problem at
   once. Compare its `volume` for a given ticker against `quote` and `aftermarket-trade`
   at the same moment.
5. Do these work for **low-float small caps**, or only large caps? Probe both.
6. What is returned for a ticker with **no pre-market activity** — zeros, nulls, stale
   previous-session values, or an error? The scanner must distinguish "not trading" from
   "no data", and a stale non-null value is the dangerous case.

> Report the outcome as an explicit verdict: **can V2 compute a meaningful `rvol_pct`,
> and from which endpoint?** If the answer is no, say so plainly — V2 then ships as a
> gap-and-headroom scanner with RVOL disabled and labelled, and that becomes the V3
> upgrade trigger. Do not manufacture an approximation from a per-trade size and present
> it as relative volume; a fabricated conviction signal is worse than an absent one.

**B. Float endpoints**
6. **`shares-float-all`** is confirmed available on Starter. Measure it: how many records,
   is it paginated, payload size (bandwidth matters — 20 GB/30 days), does it cover small
   caps, and how current is the data? This is the nightly float refresh.
7. Does `shares-float` now work for arbitrary US symbols (not just the free-tier sample)?

**C. Universe endpoints**
8. Are `stock-list` and `company-screener` unrestricted now? Capture the exact fields the
   screener returns.
9. Screener pagination and filter behaviour: page size, total available, which filters are
   honoured (`volume`, `price`, `marketCap`, `isEtf`, `isFund`, exchange, country).
10. **Measure the universe size at several pre-filter settings**, e.g.
    `price > 2 AND volume > 500000` with market-cap ceilings of $2B / $5B / $10B / none.
    Report the counts. 4B needs these numbers to size the nightly job; a market-cap ceiling
    is only a *proxy* for float, so note how over-inclusive each setting is.

**D. Limits**
11. Confirmed by support: **300 calls/minute, no daily cap**, 20 GB bandwidth per rolling
    30 days. Verify the rate limit empirically and — since bandwidth is now the binding
    quota rather than call count — **measure the payload size of every endpoint the
    scanner will use**, and project monthly bandwidth for a realistic universe and cadence.
12. Confirm whether 402 responses still occur on Starter and for which endpoints.

## Scope

1. **`scripts/probe_fmp_starter.py`** — a self-contained probe covering A–D. Structured
   output, and it must be re-runnable at different times of day (pre-market vs after-hours)
   since question A.1 and A.3 can only be answered during a live extended session.
2. **Every call goes through the existing budget guard.** Raise `FMP_DAILY_BUDGET` to a
   Starter-appropriate value via config — do NOT bypass the guard. It is now the record of
   what the tier costs.
3. **Record fixtures** for every new endpoint shape discovered (aftermarket quote with and
   without activity, `shares-float-all` sample, screener page) into `tests/fixtures/fmp/`,
   reusing the Phase 1 recorder so tests keep running offline.
4. **Extend the FMP client only as needed to probe** — typed models for the new endpoints,
   with the same error taxonomy. No scanner or pipeline changes.
5. **A findings document** at `docs/FMP_STARTER_FINDINGS.md`: every question above with the
   measured answer, the raw evidence (including the volume time-series from A.3), and an
   explicit list of what could NOT be determined and why.

## Constraints
- No changes to the scanner, alert contract, dashboard or thresholds.
- Do not deliberately exhaust the rate limit or the daily quota.
- CI must stay offline — fixtures only.
- A.1 and A.3 require a live pre-market session (04:00–09:30 ET = 10:00–15:30 CEST). If
  the probe is run outside those hours, say so explicitly in the report rather than
  inferring, and re-run during a session.

## Definition of done
1. `scripts/probe_fmp_starter.py` runs and answers A–D as far as the session allows
2. `docs/FMP_STARTER_FINDINGS.md` exists with measured answers and raw evidence
3. **An explicit verdict on RVOL**: can V2 compute a meaningful `rvol_pct`, from which
   endpoint, and with what caveats — or is Stage 2 gap-only at this tier?
4. **Question A.2/A.3 answered with a time-series**, not single samples
5. Universe counts reported for at least three pre-filter settings
6. Projected monthly bandwidth for a realistic universe and scan cadence
7. Fixtures recorded for every new endpoint shape; tests pass offline; ruff clean
8. Report closes with: which of 4B/4C's planned designs are now confirmed, which must
   change, and any newly discovered constraint
````

---

## Phase 4B / 4C (V2) — written after 4A reports

**4B — Universe expansion + nightly refresh at scale.** Two-step build (screener → float
→ `reference_data`), sized by 4A's measured counts, budget-aware and resumable.

**4C — Live snapshot provider, RVOL, cron go-live.** `FmpLiveSnapshotProvider` against the
aftermarket quote; RVOL approximation selected from 4A's volume-semantics finding and
flagged approximate everywhere; tiered cron cadence (15 min early session, 5 min from
08:00); Render backend upgraded to Starter; news/catalyst tagging.

Both depend on 4A's answers — particularly whether pre-market is covered and whether the
quote's volume is cumulative. Writing them earlier would bake in assumptions.

---

## Working notes

- One phase per session; verify Definition of done before advancing.
- The budget guard is the first thing built and the last thing bypassed — never exempt
  a "quick test" from it.
- CI never touches live FMP.
- Demo-profile output must always be visibly labelled — in logs, DB, and UI.
- **Alpaca code is removed in Phase 3.5**, between V1 shipping and the V2 (Starter)
  work — not "after V2 goes live". The schema migration is cheapest while the app has
  no users, and Phase 4 should start on a clean schema.
