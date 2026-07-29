# Trading Engine — Implementation Plan (v2)

> Companion documents: `docs/CLAUDE.md` (specification), `docs/PROMPT.md` (Claude Code
> prompts), `docs/PROJECT_REPORT.md` (stakeholder report with the V1→V4 version ladder).

---

## Objective

Build an **alerts-only pre-market universe scanner** on FMP data, deployed as Render
(backend + cron) + Vercel (frontend) + Supabase (PostgreSQL), delivered **incrementally
against FMP subscription tiers**: build everything on the free tier first, upgrade only
when a real data limitation is hit.

---

## Delivery model: app versions map to FMP tiers

| App version | FMP tier | What it is | Status |
|---|---|---|---|
| **V1** | Basic (free) | Complete software, small curated universe (43 probed symbols), EOD data only. A development environment that proves every calculation — not yet a live scanner. | **← current** (Phase 1 done) |
| **V2** | Starter ($19/mo annual) | First genuinely working scanner: real-time quotes, full US universe, intraday (regular hours only — no `extended=true`). RVOL approximate. | next |
| **V3** | Premium ($49/mo annual) | `extended=true` pre-market intraday bars → real pre-market volume, volume profiles, accurate RVOL; 1-min bars; 30y history; backtesting → validated confidence score. | target |
| **V4** | Ultimate ($99/mo annual) | Bulk delivery, global. Probably unnecessary. | unlikely |

**FMP support answers (July 2026) — both former open questions RESOLVED:**
- Starter's 5-min intraday bars do **NOT** include pre-market. The `extended=true`
  parameter (which adds pre/after-market intervals) requires **Premium** (US symbols)
  or Ultimate (global). → Accurate RVOL and pre-market volume profiles are **V3**.
- Starter's intraday chart access **is** as the comparison table shows: 5-min and
  coarser intervals, US symbols, regular trading hours only.

**V1 constraints that shape the code** (from FMP docs + pricing page):
- 250 API calls/day, hard stop (429). A persistent daily budget guard is mandatory.
- EOD data only; no intraday, no real-time.
- Most endpoints limited to a fixed sample of large-cap symbols (AAPL, TSLA, …).
- Those symbols all FAIL the real Stage-1 float filter (< 75M) — so end-to-end demos with
  real data require a **demo threshold profile** (loosened float cap) via config.
- Base URL pattern: `https://financialmodelingprep.com/stable/<endpoint>?apikey=KEY`.

**Efficient V1 call pattern:** `historical-price-eod/full` returns full daily history in
one call → compute vol_avg_20d, SMA-50/200, 20d high, prior close/high locally. Plus
`shares-float` = **2 calls per ticker per day** → ~80–100 tickers fit the daily budget.

### Measured free-tier reality (Phase 1, 25 July 2026)

Probed with a live key, not assumed. Several documented behaviours did not hold:

| Endpoint | Free tier | Notes |
|---|---|---|
| `historical-price-eod/full?symbol=` | ✅ works | 1255 daily bars for AAPL — ample for SMA-200 |
| `shares-float?symbol=` | ✅ works | `floatShares` is a count; `freeFloat` is a **percentage** |
| `quote?symbol=` | ✅ works | for sample symbols only |
| `profile?symbol=` | ✅ works | |
| `batch-quote?symbols=` | ❌ **402** | "Restricted Endpoint" — the planned cheap probe is unavailable |
| `stock-list` | ❌ **402** | Restricted Endpoint |
| `company-screener` | ❌ **402** | Restricted Endpoint — confirms universe expansion is V2 work |

- **FMP returns HTTP 402 (not 403) for both restriction kinds**, with a **plain-text**
  body, and both messages contain "not available under your current subscription". Only
  the phrasing separates them: `"Restricted Endpoint: This endpoint is not available…"`
  (fail the path) vs `"Premium Query Parameter: 'Special Endpoint : This value set for
  'symbol' is not available…"` (skip the ticker). The client classifies on that.
- **Accessible universe: 43 symbols** out of 92 probed large-cap candidates. Small caps
  (SNDL, MULN, GNS, BBIG, ATER) are correctly refused, so the probe detects negatives.
- Because `batch-quote` is restricted, **probing costs 1 call per symbol** (93 calls for
  the default list). The batch path is kept and used automatically once the key is
  upgraded — the fallback is what runs on free.
- Every accessible symbol's float is in the billions, so **all 43 fail the production
  Stage-1 float cap (< 75M)**. Phase 2's demo profile is not optional.

---

## v1-codebase status (what already exists)

Reusable: FastAPI + async SQLAlchemy + Alembic + `uv`; React 19/Vite/Zustand frontend;
client WebSocket alert broadcast; OpenAPI contract + generated TS types; ~355 tests + CI;
deployed infra (Render Frankfurt web + cron stub, Vercel, Supabase) — verified end-to-end.

Being retired: Alpaca client + stream manager; watchlist streaming model; per-tick YAML
rule engine as primary trigger; Alpaca MCP trading tools.

---

## Locked decisions

| Decision | Choice | Rationale |
|---|---|---|
| Data provider | **FMP** | Only affordable provider bundling price + volume + **float** + screener + news |
| Delivery | **Tier-staged (V1→V3)** | Spend only when a real limitation is hit |
| Trading | **None** | Alerts only, permanently |
| Local DB | **PostgreSQL** | Parity with prod (done in Phase 0) |
| Prod DB | **Supabase** | Free tier persists |
| Backend host | **Render** (web + cron) | Deployed; cron stub live |
| Frontend host | **Vercel** | Deployed |
| Scan window | **04:00 → 09:25 ET**, every 5 min | Full early session (V2+; V1 has no intraday) |
| RVOL | **Pluggable**: simple ↔ time-of-day-normalized | Normalized needs `extended=true` intraday — **confirmed Premium-only (V3)**. V2 ships an approximate RVOL, flagged on every alert; interface built in V1 |
| Scheduler | **Render Cron Job** | Provisioned (stub) |

---

## Phase roadmap (re-sequenced for tier-staged delivery)

### Phase 0 — Infrastructure Migration — ✅ DONE
Postgres everywhere; Render (Frankfurt) web + cron stub; Vercel; Supabase; CI trimmed;
full-stack connectivity verified (API healthy, DB connected).

---

### Phase 1 (V1) — FMP Client, Budget Guard & Reference Pipeline — ✅ DONE
**Tier:** free. **Goal:** the data backbone, built to free-tier reality.

- [x] FMP client against `stable/` endpoints; typed responses; retries (transient only —
      429 is never retried); typed error taxonomy
- [x] **Daily API budget guard**: Postgres-backed counter keyed on the UTC day, atomic
      conditional UPDATE, ceiling `FMP_DAILY_BUDGET` (default 230), every call logged
- [x] **Symbol probe**: empirical, with a negative control group → **43 accessible
      symbols** persisted to `universe`
- [x] Fixture recorder + replay client sharing the live parse path (CI never hits FMP)
- [x] Tables: `universe`, `reference_data`, `premarket_volume_profile` (schema only —
      needs `extended=true`, so V3), `scan_runs`, `api_budget` + Stage-1 index
- [x] Reference pipeline: float + EOD-derived metrics (2 calls/ticker), idempotent,
      resumable, budget-aware
- [x] CLIs: `refresh_reference_data.py`, `probe_fmp_symbols.py`, `fmp_budget.py`,
      `record_fmp_fixtures.py`
- [x] **RVOL interface** with `simple` and `normalized` implementations — normalized
      raises `FeatureRequiresIntraday` naming the tier it needs

**Verified end to end:** 43-symbol universe probed; 11 tickers refreshed from real EOD
data at exactly 2 calls each; same-day re-run cost 0 calls; a mid-run budget stop left
completed tickers intact and skipped the rest; 464 tests green offline; ruff clean.

### Phase 2 (V1) — Scanner Pipeline (fixture-fed where data is missing) — ✅ DONE
- [x] Stage 1 (SQL on `reference_data`) and Stage 3 (resistance math) — fully live on real EOD data
- [x] Stage 2 (gap + RVOL) — complete, fed by a snapshot scenario behind `SnapshotProvider`;
      `FmpLiveSnapshotProvider` documented and stubbed for V2
- [x] **Threshold profiles**: `production` and `demo` (loosens ONLY the float cap, so demo
      exercises the same logic); `is_demo` stamped on runs, candidates and payloads
- [x] Injectable clock, explicit ET conversion, DST tests both directions
- [x] `scan_runs` observability with a four-state taxonomy; golden-case boundary tests
- [x] CLI `scripts/run_scan.py --fixture --at ... --profile demo|production`
- [x] Risk filters (live-price floor, dollar volume) + neutral market-tape stub

**Verified:** golden fixture run pins the full funnel (11 → 7 → 4 → 2, candidates
`LOWF, EDGE`); demo profile on real reference data yields 3 Stage-3 survivors
(ADBE 15.75%, BA 7.95%, C 6.05% upside); production yields 0 and reports it as a
*successful scan of a quiet market*; 553 tests green; ruff clean.

**Decisions made during the phase:**
- **Percentages are compared at 6dp.** `105 * 1.055 - 105` computes an upside of
  5.499999999999996, which on a raw float compare rejects a candidate whose card reads
  "5.50%" against a documented 5.5% bar. Rounding first makes the displayed number and
  the decision agree.
- **Stage 3 runs on every pass, not only at 09:25.** It is pure arithmetic over data
  already in memory and the upside figure is useful earlier; `is_final_pass` marks which
  run is authoritative, and Phase 3 decides what to persist and push from that.
- **`tzdata` is now an explicit dependency.** It was transitive (via pandas), and market
  -time correctness should not rest on another package's dependency graph.

### Phase 3 (V1) — Scoring, Alerts & Dashboard — ✅ DONE
- [x] Confidence score: 5 weighted factors, config constants, per-factor breakdown,
      labelled PROVISIONAL everywhere. Null `upside_pct` degrades to a neutral fallback
- [x] v2 alert contract + persistence with per-session dedup + WebSocket broadcast
- [x] `scanner_settings` table: threshold/profile edits apply to the next scan, no redeploy
- [x] Dashboard rebuild: mobile-first alert cards with score breakdown and demo badges,
      scan-status panel where failure ≠ zero candidates, threshold editor, honest framing
- [x] OpenAPI + TS types regenerated (7 new paths, 8 new schemas)
- [x] Render cron wired to `run_scan.py --fixture --profile production`

**V1 exit criteria — all met:** the pipeline runs end-to-end on real free-tier reference
data in demo profile (10 → 10 → 6 → 3 candidates, ADBE/BA/C); every calculation is
fixture-verified; the dashboard shows real generated alerts, live over WebSocket; the
daily API budget is never exceeded (the scanner makes zero FMP calls — Stage 2 is
fixture-fed and Stages 1/3 read pre-computed reference data).

**Decisions and findings:**
- **`alerts` was extended, not replaced.** v1 columns are retained but nullable, so the
  rule-engine path and its ~100 tests keep working until Alpaca is removed. The DB column
  stays `symbol`; the API exposes `ticker` per the 4.4 contract, mapped in
  `app/schemas/scanner.py`.
- **Thresholds live in a dedicated `scanner_settings` table**, not in `rules` as section 5
  suggested. `rules.config_yaml` is free text belonging to a retired subsystem; typed
  columns keep the values validated and independent of the rule engine's removal.
- **Migration needed hand-editing.** Three NOT NULL additions to a populated `alerts`
  table required `server_default`, and autogenerate emitted an unnamed FK that made
  `downgrade` uncompilable. Both would have failed against Supabase.
- **A zero-candidate scan must still broadcast.** Gating the push on "did we persist
  anything" left a dashboard showing an earlier failure stuck on "SCANNER FAILING" until
  the next 60s poll. Failure-to-healthy is the most important transition to deliver.
- **Confidence scores are deliberately low in V1.** Demo profile + approximate RVOL +
  fixture snapshots zero out the data-quality factor by design.

---

### Phase 3.5 (V1 cleanup) — Remove Alpaca + v1 schema vestiges — ✅ DONE
**Tier:** free (no subscription needed). **Goal:** retire v1 before the V2 work starts.

- [x] Deleted `alpaca_client.py`, `stream_manager.py`, `alert_generator.py`,
      `rule_engine.py`, the market-data/rules/v1-alerts APIs, Alpaca settings, env
      vars, the `alpaca-py` dependency and every doc reference
- [x] MCP audit: **no tool was Alpaca-dependent** — they were database-backed and
      shaped around the v1 alert columns (127 references). Server deleted; see below
- [x] Dropped the v1 columns from `alerts` + the `rules` FK
- [x] Renamed `alerts.symbol` → `alerts.ticker`; mapping layer deleted
- [x] **`rules` dropped** — orphaned once `scanner_settings` superseded it
- [x] **v1-origin alert rows deleted** (23 locally), count logged by the migration
- [x] Round-trip test seeds BOTH origins; downgrade restores the v1 columns nullable

**Delivered as three commits**, one revert point each: MCP removal, Alpaca removal,
schema migration. MCP went first because it imported `app.models.rule`, which the
Alpaca commit would otherwise have left dangling.

**Decisions:**
- *MCP server deleted, not ported.* It is developer tooling — section 1 defines the
  end user as a non-technical trader on a dashboard — and `PLAN.md` Phase 7 already
  listed "MCP server decision" as open. This resolves it.
- *`rules` dropped.* Phase 3's `scanner_settings` gave thresholds typed columns and
  write-time validation; `rules` held free-text YAML for the retired engine and was
  read by nothing.
- *v1-origin rows deleted, not kept.* Every column giving them meaning is dropped by
  the same migration, and both read paths filter on `session_date`, so they would be
  unreachable husks. Reasoning in the migration docstring; loss noted in README.

**Verified:** `run_scan.py --fixture --profile demo --at "2026-07-28 09:25 ET"`
produces byte-identical output before and after; dashboard unchanged end to end;
333 backend + 45 frontend tests pass; ruff and eslint clean.

**Why here and not later:** this is DDL on a populated table. Right now it holds a
handful of rows and has zero users — from V2 onward the end user checks the dashboard
daily and every migration carries a real rollback cost. The round-trip test
infrastructure is also freshly built. And the "keep Alpaca as a fallback smoke test"
rationale has already expired: the deployed dashboard reports `Alpaca — Disconnected`,
and the real smoke tests are `seed_test_alerts.py` and the fixture scan.

**Done when:** no Alpaca anywhere; `alerts` is v2-only with a `ticker` column; scanner
output byte-identical before and after; round-trip + downgrade pass on populated data.

---

### Phase 4 (V2 — requires FMP Starter) — Go Live

**Verify before subscribing** (from the V1 build):
1. That the pre/after-market quote endpoints expose a usable pre-market **volume** figure
   at all — the RVOL approximation depends on it, and FMP's docs do not say. If they do
   not, V2 ships gap% without RVOL conviction, which weakens Stage 2 considerably.
2. That `batch-quote` really is unrestricted on Starter (it is 402 on free). Universe
   expansion and the cheap symbol probe both assume it.
3. Whether `company-screener` returns float, or only market cap. Stage 1 needs float, and
   the free tier could not be probed for this.

- [ ] Universe expansion: directory + screener endpoints → real low-float universe
- [ ] Real-time + pre/after-market quote endpoints → live pre-market gap%
- [ ] **RVOL approximation** (no pre-market bars on Starter — confirmed): validate
      empirically what the quote endpoints expose for pre-market volume; implement the
      best available approximation behind the RvolCalculator interface; **flag every
      alert's RVOL as approximate** in payload + UI
- [ ] Wire the cron job to the real scan (every 5 min, 04:00–09:25 ET); upgrade Render
      backend to Starter (always-on)
- [ ] News/catalyst tagging; first weeks of live-alert observation (open questions #3–4)
- [ ] Track in live use whether volume conviction is the weak link — that observation is
      the explicit V3 upgrade trigger

### Phase 5 (V2/V3) — Enrichment
Sector relative strength, bid-ask spread, short interest (slow signal), halt-risk flag,
gap-and-go history.

### Phase 6 (V3 — requires FMP Premium) — Accurate RVOL, Backtesting & Calibration
`extended=true` pre-market bars → measure real pre-market accumulated volume; build the
per-ticker pre-market volume profiles; switch RVOL to `normalized`; historical replay
harness; outcome labelling (+5% within first hour?); per-signal hit rates; fitted
confidence weights; threshold sensitivity sweep; results published in dashboard.

### Phase 7 — Hardening (before reliance)
Auth on dashboard; push/email delivery at 09:25 ET; FMP usage monitoring; scan-failure
alerting; MCP server decision.

---

## Sequencing rules

1. Phases 1–3 complete **entirely on the free tier** — no subscription needed until Phase 4.
2. Build the budget guard **before** any other FMP call path.
3. Probe accessible symbols before designing around them.
4. CI never touches live FMP. Fixtures always.
5. One phase per Claude Code session; verify "done when" before advancing.
5b. **Phase 3.5 runs before Phase 4**, on the free tier, while waiting on FMP support.
   Schema cleanup is cheapest with zero users, and Phase 4 should begin on a clean
   schema — the live snapshot provider is the code most likely to trip over a column
   stored as `symbol` but exposed as `ticker`.
6. FMP support questions #1–2: **answered** (see top of this file). Remaining
   pre-Starter check: none — subscribe when V1 ships.

---

## Known risks

| Risk | Impact | Mitigation |
|---|---|---|
| ~~Free-tier symbol sample differs from docs~~ **CONFIRMED** | V1 universe is 43 symbols, and `batch-quote`/`stock-list`/`company-screener` are 402-restricted | Probe measured it (Phase 1); universe lives in the `universe` table, not in code |
| 250/day exhausted mid-pipeline | Partial refresh | Budget guard + resumable jobs; 2-calls/ticker design |
| Starter RVOL approximation too weak in practice | Alert quality suffers at V2 | Flag approximate RVOL on every alert; treat this observation as the V3 upgrade trigger |
| Render cron UTC/DST drift | Wrong-hour scans | Explicit ET conversion + DST tests (Phase 2) |
| Silent scan failure | Looks like a quiet market | `scan_runs` + distinct UI states + failure alerting |
| Demo profile confused for production | Misleading alerts | Profile name stamped on every scan run and alert |

---

## Legacy notes

- `backup.sql` moved out of the repo; `*.sql` gitignored; never restore into Supabase.
- **Alpaca removal is Phase 3.5** — settled. Earlier drafts variously said "after Phase 2",
  "once the scanner proves out" and "after V2 goes live"; those are superseded.
- Migrations are the highest-risk surface in this project (two production issues in three
  phases). Every schema change gets a round-trip test on POPULATED data, and
  `pg_dump` before any downgrade is run against a real database.
