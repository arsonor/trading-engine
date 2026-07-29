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

## Phase 4+ (V2 — FMP Starter) — not yet written

Written after V1 ships. Both former FMP open questions are answered (see PLAN.md top):
no pre-market intraday on Starter (`extended=true` = Premium), and intraday access
otherwise as the comparison table shows. V2 scope therefore centres on: universe
expansion, live pre-market gap% via the pre/after-market quote endpoints, an explicitly
flagged RVOL approximation behind the RvolCalculator interface, cron go-live, and
observing whether volume conviction justifies the V3 (Premium) upgrade. Scope in
`docs/PLAN.md` Phase 4.

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
