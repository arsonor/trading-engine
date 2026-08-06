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

## Delivery model — UPDATED 5 August 2026: Premium purchased, Starter skipped

| App version | FMP tier | What it is | Status |
|---|---|---|---|
| **V1** | Basic (free) | Complete software, 43-symbol universe, EOD only. Proves every calculation; not a live scanner. | ✅ **DONE** (Phases 0–3.5) |
| **V2** | **Premium — $69 month-to-month, purchased 5 Aug 2026** | The real scanner: full US universe, `extended=true` pre-market bars → genuine pre-market volume, time-of-day-normalized RVOL, batch-quote, 1-min bars, 30y history. | **← current** |
| ~~Starter~~ | ~~$19/mo~~ | **SKIPPED.** No pre-market volume (`extended=true` is Premium-only) and the end user declared pre-market volume non-negotiable. Buying it would have shipped a gap-only scanner. | skipped |
| **V3** | Premium (same key) | Backtesting + confidence-score calibration. No new subscription — same tier, deeper work. | after V2 |
| V4 | Ultimate ($99/mo) | Bulk delivery, global. Almost certainly unnecessary. | unlikely |

**What FMP support confirmed about Premium** (asked before purchase):
- `extended=true` adds pre-market and after-market intervals to intraday charts.
- It applies to **any US symbol with intraday data** — not filtered by market cap, float or
  liquidity. Low-float small caps are covered. US symbols only.
- Premium also unlocks `batch-quote` (402 on free and Starter), 1-minute bars, 750
  calls/min, 30 years of history, and technical indicators.
- 750 calls/minute, **no daily cap**, 50 GB per rolling 30 days → **bandwidth is the
  binding limit, not call count.**

**⚠ None of this is measured yet.** Roughly half the vendor claims taken on trust in this
project have needed correction once probed (see `docs/TIINGO_VS_FMP_EVALUATION.md` §11).
**Phase 4A measures before Phase 4B builds.**

### The budget guard is re-tuned, not removed

`FMP_DAILY_BUDGET` (default 230) was built for the free tier's 250/day hard stop. Premium
has no daily cap, so the guard's purpose changes from *avoiding a hard failure* to
*observability and runaway protection*. Keep it, raise the ceiling, and add **bandwidth
tracking** — that is now the real limit.

**Superseded (kept for context):** FMP support's July answers established that Starter's
5-min intraday bars do **not** include pre-market and that `extended=true` requires Premium.
That finding is what caused Starter to be skipped entirely.

**V1 constraints (historical — the free tier the app was built against):**
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

Retired — all gone as of 2 August 2026 (Phase 3.5 plus the watchlist deletion): Alpaca
client + stream manager; watchlist model, API and table; per-tick YAML rule engine and the
`rules` table; the MCP server.

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
| RVOL | **Pluggable**: simple ↔ time-of-day-normalized | Normalized needs `extended=true` — **now available (Premium purchased)**. V2 targets normalized directly, subject to 4A confirming pre-market bar coverage |
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

**Carried over from Phase 3.5 — ✅ DONE (2 August 2026), no subscription needed:**
- [x] **Watchlist deleted.** Model, API and its router registration, repository, schemas,
      frontend store slice and components, tests, and the `watchlist` table via migration
      `544a7fbf3445`. It had no UI, nothing in the v2 spec referenced it, and the scanner's
      premise is scanning the whole universe rather than a curated list — yet every schema
      change still had to account for it. `docs/CLAUDE.md` §5 records why. Same reasoning as
      the MCP removal: git keeps it if a favourites feature ever earns a place on the
      roadmap.
- [x] **RLS enforced, not remembered.** Migration `dbdf5784db31` enables row-level security
      on all eight `public` tables including `alembic_version`, with **zero policies** — a
      deny-all posture for the Supabase Data API, which the backend is unaffected by because
      it connects as the table owner. `tests/integration/test_rls.py` fails (never skips) when
      any `public` table lacks it, so the V2 migrations cannot ship an exposed table. The
      migration is idempotent: production had already been fixed by hand.
- [x] **Phase 4-prep (b) — three cleanups.** CLI scripts now dispose the DB engine through
      `run_cli()`; threshold summaries are derived at call time, so the demo banner reports
      *effective* rather than nominal values; and `scanner_settings.overrides_json` is scoped
      per profile (migration `9c3b774f629a`), so a production override can no longer silently
      defeat the demo float cap and present as a quiet market — the pipeline now names that
      misconfiguration instead of reporting a clean empty scan.

### ~~FMP Starter capabilities~~ — SUPERSEDED (Starter was skipped; Premium purchased 5 Aug 2026)

> Kept as the record of why Starter was rejected. Its conclusion — that Starter has no
> pre-market volume source — is exactly what forced the jump to Premium. Everything below
> about "the pre-market volume problem", the 300/min budget arithmetic, and the
> aftermarket-quote candidates is **no longer the plan**: `extended=true` supersedes all of
> it. The one item that carries forward is §6.1 (free-tier `shares-float` works for
> arbitrary small caps), which remains an unexplained contradiction with FMP support and is
> worth re-checking during 4A.

> **⚠ A measured finding contradicts the free-tier assumption below.** The Tiingo probe
> (4 Aug 2026, `docs/TIINGO_PROBE_FINDINGS.md` §6.1) established that **FMP's
> `shares-float` is NOT restricted to the ~43-symbol free sample** — 64 of 70 arbitrary
> small caps returned real floats on the **free** tier, including names at 32,174 and
> 48,821 shares. The ~43-symbol limit applies to `quote` and `historical-price-eod`.
> `reference_data` holds only megacaps because the universe was built from *quote*
> accessibility, not because float was unavailable.
>
> **Consequence:** a genuine low-float universe may be buildable on the free tier today.
> Phase 4A must therefore answer a sharper question before any subscription is bought:
> **what does Starter provide that the free tier plus `shares-float` does not already?**
>
> The probe also found that free-tier **Tiingo** already returns 5-min pre-market bars
> with volume from 04:00 ET across 34 sessions in one request — the data this plan
> attributes to FMP Premium's `extended=true`. Normalized RVOL may be a data-source
> choice rather than a tier upgrade. See `docs/TIINGO_VS_FMP_EVALUATION.md`.

| Question | Answer | Consequence |
|---|---|---|
| Do pre/after-market quote endpoints return **volume**? | **Partly — and not where we needed it.** The *Aftermarket Quote* endpoint returns volume, but it is **post-close only**; it does **not** cover pre-market. There is **no dedicated pre-market quote endpoint**. | The original Stage-2 data source does not exist on any tier. Pre-market price must come from **Aftermarket Trade** instead. See "the pre-market volume problem" below. |
| Is `batch-quote` available on Starter? | **No** — batch quote and batch quote short are **Premium-only**. One symbol per request. | Every live snapshot costs 1 call per ticker per pass. |
| Does `company-screener` return float? | **No** — market cap, price, volume, beta, sector, industry, country, ETF/fund flags only. Float comes from `shares-float` or `shares-float-all`. | Universe build is **two-step**: screener pre-filters on proxies, float fetched separately, real Stage-1 cap applied locally. |
| Is `shares-float-all` (bulk float) available on Starter? | **Yes** — bulk float for many companies in one request (`freeFloat`, `floatShares`, `outstandingShares`), US symbols. | **Nightly float refresh collapses from ~N calls to ~1.** Removes the largest chunk of the nightly job. |
| Daily request cap on Starter? | **No daily cap** — 300 calls/minute, plus a 20 GB / rolling-30-day bandwidth limit. | The tiered-cadence workaround is **no longer required for quota reasons**. 300/min is still a pacing constraint per pass, and bandwidth now matters more than call count. |

**What FMP recommends for pre-market**, in their own words:
- *Quote API* → regular hours only
- *Aftermarket Trade* → real-time pre-market **trading activity**
- *Historical chart 5min + `extended=true`* → pre-market OHLCV bars — **but `extended=true`
  is Premium-only**, so this path is V3.

### The pre-market volume problem (the open risk for V2)

A **trade** endpoint and a **quote** endpoint carry different payloads. A trade record is
typically last price + last trade size + timestamp — the size of *one transaction*, not
cumulative session volume. If Aftermarket Trade behaves that way, then on Starter:

- Pre-market **price** → available → `gap_pct` works ✅
- Pre-market **cumulative volume** → possibly unavailable → `rvol_pct` uncomputable ❌

That would reduce Stage 2 to a gap filter with no conviction signal — the exact scenario
flagged as V2's main risk. It is **not settled**: three candidate sources could still
supply cumulative pre-market volume, and all three are cheap to measure rather than debate.

| Candidate | Why it might work | Why it might not |
|---|---|---|
| `aftermarket-trade` payload | May carry a running/session volume field alongside last trade size | "Trade" endpoints usually report per-transaction size only |
| `quote` → `volume` field | Day-cumulative volume fields often begin accumulating pre-open, even when the *price* is stale | FMP says Quote is "regular hours only" — that may apply to the whole payload |
| `company-screener` → `volume` field | Returns many symbols per call — would solve the volume **and** the batch problem at once | Screener volume may be previous-close or delayed |

**Any one of these working salvages RVOL at V2.** Phase 4A measures all three during a
live pre-market session before a line of V2 code is designed.

**Verdict: Starter still delivers a working scanner — with one unresolved question that
sets its ceiling.** Stage 1 (real float via bulk `shares-float-all`), Stage 3 (resistance
math) and Stage 2's `gap_pct` all work. Whether Stage 2 also gets `rvol_pct` depends
entirely on the pre-market volume question above. Worst case, V2 ships as a gap-and-
headroom scanner with RVOL disabled and clearly labelled — still a real filter, but
missing the conviction signal, and that becomes a much sharper V3 trigger.

### The call-budget arithmetic (Starter = 300 requests/minute)

Without `batch-quote`, cost scales linearly with universe size:

| Workload | Calls | At 300/min |
|---|---|---|
| Nightly: screener sweep | a few (paginated) | seconds |
| Nightly: `shares-float` per survivor | 1 × N | — |
| Nightly: `historical-price-eod/full` per survivor | 1 × N | — |
| Nightly total at N = 2,000 | ~4,000 | ~14 min |
| Per scan pass: 1 quote × Stage-1 candidates | 300–800 | 1–3 min |
| Full session at 65 passes × 500 | ~32,500/day | — |

Two design consequences:

1. **Over-inclusive screener pre-filter, exact filtering locally.** The screener cannot
   see float, so it filters on proxies (`volume > 500K`, `price > $2`, a *generous*
   market-cap ceiling as a float proxy). Anything it wrongly excludes is never seen again,
   so the pre-filter must err heavily toward inclusion; the real `float < 75M` cap is
   applied in SQL afterwards.
2. **Nightly float is now ~1 call**, not N — `shares-float-all` is available on Starter.
   The nightly job reduces to: one screener sweep + one bulk-float call + one
   `historical-price-eod/full` per survivor.

With **no daily cap**, tiered scan cadence is no longer required to conserve quota. It may
still be worth adopting to reduce bandwidth (20 GB / 30 days) and pass duration — decide
with 4A's measured payload sizes, not in advance.

### Still to confirm — all three FMP support questions ANSWERED (29 July 2026)

Nothing further is blocked on FMP support. The remaining unknowns are **empirical** and
belong to Phase 4A: does anything on Starter expose cumulative pre-market volume, and
what exactly does Aftermarket Trade return?

---

### Phase 4A (V2) — Premium capability probe **← NEXT, run on a live pre-market session**
**Tier:** Premium (active). **Writes no product code.**

Measures what Premium actually delivers before anything is built on it. Gated on a live
pre-market window (04:00–09:30 ET = 10:00–15:30 CEST). Deliverable: a probe script plus
`docs/FMP_PREMIUM_FINDINGS.md`.

- [ ] **`extended=true` — the decisive test.** Does it return pre-market bars? From 04:00
      ET or later? For genuinely low-float small caps, or only liquid names? Is `volume`
      per-bar (summable to a cumulative session total)?
- [ ] **Guard against the PAVS failure mode** found in the Tiingo probe: sample repeatedly
      and check whether any cumulative series *decreases* mid-session. A silent reset
      produces a plausible low RVOL, not an error.
- [ ] Intraday **history depth** — how many days of extended-hours bars? ≥20 sessions is
      required for volume profiles; more is needed for V3 backtesting. The "30 years"
      figure refers to daily bars.
- [ ] `batch-quote` — confirm available; max symbols per request; payload size
- [ ] `shares-float-all` — record count, payload size, small-cap coverage
- [ ] `company-screener` — fields, pagination, and **universe size at 3+ pre-filter
      settings** (price > $2, volume > 500K, market-cap ceilings). 4B needs these numbers.
- [ ] Rate limit + **bandwidth projection** for a realistic universe and cadence (50 GB/30d)
- [ ] Fixtures recorded for every new endpoint shape

**Done when:** the findings document answers each question with measured evidence, states
plainly whether normalized RVOL is achievable, and lists which 4B/4C designs must change.

---

### Phase 4B (V2) — Universe expansion + nightly refresh at scale
**Depends on:** 4A's measured numbers.

- [ ] Two-step universe build: `company-screener` pre-filter (over-inclusive — it cannot
      see float, so anything it wrongly excludes is never seen) → `shares-float-all` →
      exact `float < 75M` applied locally in SQL
- [ ] Nightly `reference_data` refresh at real universe scale, budget- and
      bandwidth-aware, idempotent, resumable
- [ ] **Retire the demo threshold profile's reason to exist** — production thresholds now
      return real candidates. Keep the profile mechanism; stop needing it.
- [ ] Raise `FMP_DAILY_BUDGET`; add bandwidth tracking to the guard
- [ ] Round-trip migration tests on populated data for any schema change

---

### Phase 4C (V2) — Live snapshot provider, RVOL, cron go-live
**Depends on:** 4B.

- [ ] `FmpLiveSnapshotProvider` implementing the Phase-2 `MarketSnapshot` interface —
      `extended=true` intraday bars summed from 04:00 ET for cumulative pre-market volume,
      via `batch-quote` where it helps
- [ ] **Build `premarket_volume_profile`** (5-min buckets × 20 sessions) from historical
      extended-hours bars → switch `RVOL_MODE` to `normalized`
- [ ] **Decreasing-volume guard**: treat a mid-session drop in cumulative volume as a data
      fault, not a measurement (Tiingo-probe lesson; do not assume FMP is immune)
- [ ] Market-tape check (index/futures) replacing the V1 neutral stub
- [ ] Wire the Render cron to the real scan, 04:00–09:25 ET; **upgrade the Render web
      service to Starter ($7/mo)** for always-on operation
- [ ] **Move migrations to `preDeployCommand`** — the pre-deploy hook requires a paid
      instance, which this upgrade provides
- [ ] News/catalyst tagging
- [ ] First weeks of live observation: alerts per morning, threshold calibration

> **Migration strategy note.** Moving `alembic upgrade head` out of `startCommand` into
> `preDeployCommand` depends on the Render Starter upgrade above — the pre-deploy hook is
> only available on paid instances, and `render.yaml` still has the web service on
> `plan: free`. The two changes land together. Today migrations run on every container
> start, serialised by a `pg_advisory_xact_lock`; moving them means a bad migration stops
> the **deploy** rather than a **running service**. The exact change is written up under
> "Migration strategy" in `README.md`.

---

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
| Supabase RLS on public tables | Supabase flags any table in `public` without Row-Level Security as a critical issue — without it, anyone holding the project URL + anon key can read/write via the auto-generated Data API | This project never uses the Supabase Data API (the backend connects directly as `postgres`, which bypasses RLS). Fix: enable RLS with **no policies** on every public table — denies the Data API, leaves the app unaffected. Every future migration must do the same for new tables |
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
