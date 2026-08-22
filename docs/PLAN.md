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
| Scan window | **04:15 → 09:25 ET**, tiered (60/30/15/5 min) | Full early session, sampled by measured value (V2+; V1 has no intraday) |
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
  end user as a non-technical trader on a dashboard — and `PLAN.md`'s hardening phase (then Phase 7, now Phase 6) already
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

### Phase 4A (V2) — Premium capability probe — ✅ DONE (6 August 2026)

**Verdict: green light.** `extended=true` returns pre-market bars from **exactly 04:00 ET**,
for low-float small caps (smallest float measured: 13,696 shares) as well as megacaps.
Quiet tickers return an **empty array**, not stale bars, so "not trading" and "no data" are
distinguishable by row count. History goes back to at least 2016, so **normalized RVOL is
unblocked** — it was scheduled as V3 work gated on data availability; the gate is open.
Full evidence: `docs/FMP_PREMIUM_FINDINGS.md`.

**Three measured facts that change the 4B/4C design:**
1. **`batch-quote` is useless for pre-market** — it works and takes 1,000 symbols, but during
   the pre-market window it returns the *previous* session's close. The live snapshot must be
   per-ticker `historical-chart/5min?extended=true`. Affordable because the real Stage-1
   universe is **554 tickers**, not thousands: ~0.7 min per pass at 750/min, ~15% of the
   50 GB monthly bandwidth.
2. **`volume` is per-bar, not cumulative** — `volume_premarket_accumulated` is a **sum over
   bars**, never a field read.
3. **49.4% of bars are revised upward after publication** (89 of 180; median +24.2%, p90
   +100%, worst +7,156%), and **all revisions settle within 7 minutes of bar close**. Bounded
   and cheaply fixable: exclude the most recent two bars. The exclusion window must be
   **config-driven** — 7 minutes comes from one ordinary session.

> **The coupling to watch in 4C:** the live RVOL numerator and the volume-profile denominator
> must use the **same settled-bar definition and the same clock time**. A profile built from
> fully-revised history divided by a live sum containing provisional bars biases RVOL low by
> construction, straight onto the `rvol_pct > 10` gate — invisible until alert counts come in
> mysteriously low.

**Also measured:** `shares-float-all` = 8 calls / 5.2 MB for 19,569 US symbols with float
(11,504 under 75M); `company-screener` returns 15 fields and no float, 1,880 US rows at
price > $2 and volume > 500K; per-request row cap truncates long ranges, so profile building
paginates by week; no daily call cap, 750/min, bandwidth is the real limit.

---

### Phase 4B (V2) — Universe expansion + nightly refresh at scale — ✅ DONE (7 August 2026)
**Depends on:** 4A's measured numbers.

- [x] Two-step universe build: `company-screener` pre-filter → `shares-float-all` → exact
      `float < 75M` applied locally in SQL
- [x] **Universe size discovered nightly, never hardcoded**, with change detection
- [x] Nightly `reference_data` refresh at real scale, budget- and bandwidth-aware,
      idempotent, resumable
- [x] **`premarket_volume_profile` populated** — 5-min buckets × 20 sessions, paginated by
      week, `sessions_sampled` recorded
- [x] **Shared, config-driven settled-bar helper** (`app/services/bars.py`), used by the
      profile builder and later by 4C's live path
- [x] `FMP_DAILY_BUDGET` raised to 20,000 (runaway protection, not a vendor limit — Premium
      has no daily cap); bandwidth tracking added; `docs/CLAUDE.md` §6 updated
- [x] Round-trip migration test on populated data; RLS holds on the new table

**Measured:** 3,948 maintained universe → **694 Stage-1 eligible**. 695 profiles built, 691
with ≥20 sessions, 0 thin. 38,609 profile rows. Full nightly cycle ~6,900 calls / 453 MB.
Same-day reference refresh: 0 calls, 75 s.

> **⚠ The monthly figure originally stated here was wrong by a factor of ~18, and it sent
> two phases of optimisation at the wrong target.** This paragraph read "453 MB — **0.53 GB
> per 30 days, 1.1% of the allowance**". 453 MB is the cost of **one night**, and the
> nightly cron runs 22 weekdays a month: the real draw at that rate was **~9.7 GB / 30 days,
> ~19% of the allowance**. The per-run measurement was sound; only the extrapolation was
> not. Corrected 21 August 2026 from `api_budget`, which records calls and bytes per UTC
> day.
>
> **The nightly job is ~92% of everything this project spends**, and the tiered cadence,
> the 04:15 window and the whole 4C bandwidth argument were fought over the other 8%. Per
> weekday, measured by subtracting the scanner's own `bytes_used` from the day's total:
>
> | | scanner | nightly | total | × 22 | % of 50 GB |
> |---|---:|---:|---:|---:|---:|
> | 11–17 Aug | 46.3 MB | 437.9 MB | 484 MB | 10.4 GB | **20.8%** |
> | 18–20 Aug | 20.6 MB | ~245 MB | 266 MB | 5.7 GB | **11.4%** |
>
> Still comfortably inside the allowance — this is a documentation correction, not an
> operational problem. But it inverts the priority: **the next bandwidth work, if any is
> ever needed, is the nightly reference refresh, not the scan.**
>
> One limit on attribution: `api_budget` is one row per UTC day shared by both crons, so
> the nightly figure is obtained by subtraction and the profile build cannot be separated
> from the reference refresh. Only `universe_runs.bytes_used` is attributable on its own.
> Splitting the rest would need per-job accounting that does not exist yet.

**Four things found by measuring rather than assuming:**
1. **The screener's `volume` is session-so-far, not a daily average** — 1,880 rows at 04:22
   pre-market versus 159 at 09:33. Filtering the universe on it would have made membership
   depend on *when the cron happened to fire*: a non-deterministic universe with no code path
   explaining it. Liquidity is now filtered locally against `volume_avg_20d`, where the spec
   always meant it to live.
2. **Unbounded EOD history costs 19.2 GB/month.** The deepest metric needed is SMA-200;
   bounding the request to 400 days cuts it to 4.2 GB.
3. **The float cap must not be baked into the universe build.** `float < 75M` is a
   per-profile, user-editable threshold — hardcoding it meant a dashboard edit would do
   nothing until someone rebuilt the universe, and it silently broke the demo profile. The
   universe uses a wide configured cap; Stage 1 applies each profile's own.
4. **A real concurrency bug**, hit during the build: two profile runs raced on
   delete-then-insert and died on the unique constraint, leaving a profile half-written. On
   Render a slow nightly job meeting the next one reproduces this. Fixed with
   `ON CONFLICT DO UPDATE`.

---

### Phase 4C (V2) — Live scanning — ✅ DONE (7 August 2026), observation stage running
**Depends on:** 4B. **The scanner is on.**

- [x] `FmpLiveSnapshotProvider` — one `historical-chart/5min?extended=true` call per
      Stage-1 candidate, summed over settled bars. **NOT via `batch-quote`**: 4A measured
      that it returns the *previous* session's close during pre-market, so no batch route
      to live pre-market state exists. Bounded concurrency plus a pacer that limits calls
      *started* per minute, not merely in flight
- [x] **`RVOL_MODE=normalized`** against the profiles 4B built, with the **settled-bar
      symmetry rule**: numerator and denominator read the same clock instant. Keying the
      profile lookup off the scan time instead would understate every ticker, land on the
      `rvol_pct > 10` gate, and produce no symptom beyond missing alerts
- [x] Per-ticker fallback to simple RVOL, flagged, when a profile is missing or thin —
      a newly-listed name is not dropped for lacking a profile it cannot have yet
- [x] **Decreasing-volume guard** (Tiingo-probe lesson), plus volume-sanity and
      **split-distortion** guards. The last one fired immediately on real data
- [x] Market-tape check replacing the neutral stub; degrades to "not measured", never
      aborts a scan
- [x] **Alert provenance** — `bars_settled_through`, `provisional_bars_excluded`,
      `profile_sessions_sampled`, exposed via the API. Without these V3 cannot tell a bad
      call from data revised after the fact
- [x] Render web on **Starter**; migrations moved to **`preDeployCommand`**
- [x] Cron wired to the real scan, `--fixture` dropped

**Measured, one full live pass:** 60.2 s, 672 calls, 10.2 MB. Funnel 3,948 → 671 → 62 →
30 → **30 candidates**. 48 tickers not trading yet; 14 integrity findings across 7 tickers.

> **The 10.2 MB is real but was extrapolated wrongly** — corrected 17 August 2026, from
> per-pass `bytes_used` across six live sessions. That pass was an `--at` replay, and for a
> *past* session the intraday endpoint returns the whole extended day (~190 bars per
> ticker); a live pass asks only for the bars up to now, ~65 at 09:25. Measured live cost is
> **0.05 MB at 04:05 rising to 1.67 MB at 09:25, 48.5 MB a session** — so the monthly
> projection built on 10.2 MB × 66 passes (14.1 GB live, 23.6 GB total, "~47% of
> allowance") overstates the live scan by roughly an order of magnitude. Actual live draw is
> ~1.0 GB/month, ~2.0% of the 50 GB allowance.
>
> **The call count settles which input moved, and it is not the universe** — measured
> 18 August 2026 over seven sessions: a live pass makes **737 calls against 4C's 672**, so
> the Stage-1 set has *grown* ~10% rather than shrunk, and the whole gap is payload:
> **15.2 KB a call** in the replay against **2.27 KB** at a live 09:25, a factor of **6.7**.
> The bar-window ratio above accounts for only ~2.9 of that; the rest is *coverage*. A
> replay returns regular-hours bars too, when every ticker prints every five minutes, while
> in pre-market most Stage-1 small caps print sparsely — ~138 bars a ticker in the replay
> against ~20 live, not the ~65 the clock allows. The corrected figures are therefore
> conservative: they were measured on a universe 10% larger than the one that produced the
> 10.2 MB.

**Still open — carried into observation and Phase 5:**

> **Order matters.** The split-adjustment hotfix is **blocking** — do not remove `--dry-run`
> until it lands. Sequence: hotfix → re-run nightly refresh → verify the 7 known-bad tickers
> → observe several sessions → promote. Prompts for all three items are in `docs/PROMPT.md`.

- [x] **✅ RESOLVED (8 August 2026) — implausible reference data is now suppressed.**
      **The premise was wrong, and measuring it was the whole value of the hotfix.**
      `historical-price-eod/full` is **already split-adjusted**. FFAI's June bars return
      42.42 with volume 97,942, while the raw tape (`historical-price-eod/non-split-adjusted`)
      shows 0.2828 with volume 14,691,299 — price and volume ratios both exactly **150.0**,
      which only holds if `full` is the adjusted series. **Five of the seven flagged tickers
      had no split at all.**

      These are **real collapses**: FFAI fell 32.06 → 4.38 in twenty sessions, WETO
      67.07 → 5.77, CAPR 22.50 → 4.18. The reference data was correct all along and the
      540% upside is arithmetically right — it is *strategically* meaningless, because a
      50-day average seven times the price is where the stock used to trade, not something
      pulling it back. So there was nothing to fix in the data, and a filter was the only
      available answer.

      Delivered: `scan_upside_max` (100%) and `scan_price_regime_break_ratio` (3×) as
      **risk filters** (`docs/CLAUDE.md` §4.3), rejecting with named reasons
      (`implausible upside`, `price regime break`) counted separately in `scan_runs` and
      reported in the scan output. Stage arithmetic untouched. The 4C guard was renamed
      `split_distortion` → `price_regime_break`, since it identified the right tickers for
      the wrong reason.

      **Measured on a live pass:** 30 → **29 candidates**, FFAI suppressed. The top row is
      now BCAR at 95.6% rather than FFAI at 540%. Note 14 integrity findings across 7
      tickers but only **1** suppression — the other six never reached Stage 3, so they
      were already being rejected on gap or RVOL.
- [x] **✅ FIXED (8 August 2026) — the observation window was recording nothing.**
      Phase 4C specified "full pipeline, `scan_runs` recorded, no alerts persisted" and
      implemented it by reusing `--dry-run`, which has meant *touch nothing* since Phase 2.
      The cron ran a full live scan every five minutes and discarded the result: **zero
      `scan_runs` rows for the entire observation window**, and no basis on which to judge
      the thresholds. The `render.yaml` comment described behaviour the code did not have.

      The capability already existed as `--no-persist` — the cron simply used the wrong
      flag. Renamed to **`--no-alerts`** (the old name is a deprecated alias, since
      "persist *what*?" is the ambiguity that caused this), and the three modes are now
      explicit and recorded on the `scan_runs` row: `live` / `observation` / `dry_run`.
      `--dry-run` keeps its original meaning and wins when both are given.

      The mode is surfaced in the CLI header, on the API's `ScanRun`, in the OpenAPI
      contract, and as a "no alerts" badge on the Scans page — because during observation a
      perfectly healthy run produces zero alerts by design, which is otherwise
      indistinguishable from a quiet market.
- [x] **Promote the cron to live** — ✅ **DONE.** `--no-alerts` removed from `render.yaml`.
      Alerts now persist and broadcast from every pass. Promoted after three observation
      sessions (**10–12 August 2026**) showed a stable pipeline, sane candidate counts and
      zero failures. The change landed at 20:14 CEST on the 12th, after that morning's
      window, so **13 August is the first session whose alerts persisted** — the date the
      observation record below begins.
- [x] **09:25 authoritative pass** — ✅ **DONE.** It had never executed in production:
      Render's 10–45 s scheduler latency meant the 13:25 UTC run started at 09:25:10 ET, and
      a full-timestamp comparison put it outside a window ending at 09:25:00. The log read
      "09:25 is outside the 04:00-09:25 window". Fixed by comparing at **minute resolution**
      — the same correction made in Phase 2 for percentage thresholds, and for the same
      reason: the value displayed and the value decided on must be the same value. Verified
      12 August: 13:25 completes with real work (65 → 30 → 30), 13:30 skips. Boundary exact.
- [x] **`skipped` runs now recorded** — ✅ **DONE**, alongside the boundary fix.
      `ScanRunStatus.SKIPPED` was defined and documented but never written, so querying for
      it returned nothing and could not distinguish "cron fired and correctly skipped" from
      "cron never fired". Run accounting is now complete: **84 scheduled = 66 completed + 18
      skipped**, skips exiting in ~0.05 s against ~65 s for real work.
- [x] **Tighten `scan_upside_max`?** — ✅ **CLOSED, no change needed.** The question was
      whether a ~2× upside survivor (BCAR at 95.6%, just under the 100% ceiling) meant the
      collapsed-stock pathology had merely moved one notch down. It has not: the confidence
      score's upside factor **saturates** at `upside_min × score_upside_saturation_multiple`
      = 5.5 × 3.0 = **16.5%**, above which it clamps to 1.0. BCAR at 95.6% therefore scores
      identically on that factor to a stock with 17% headroom — being collapsed buys no
      ranking advantage, and the dashboard sorts by confidence, not upside.
      Three independent barriers now apply: `price_regime_break` rejects the extreme cases
      outright, the factor saturates, and `score_data_quality` applies
      `score_penalty_null_upside`. `scan_upside_max = 100` stays generous as a backstop
      against absurdity rather than the primary defence — tightening it would risk excluding
      a legitimate post-crash retrace for no ranking benefit.
      *(RVOL and liquidity saturate too, liquidity on a log scale, so no single factor can
      dominate through sheer magnitude.)*
- [x] **Threshold calibration** — not needed on current evidence. Three sessions produced
      1–32 candidates per pass with a coherent intraday ramp, tracking market conditions
      rather than emitting a constant. Thresholds stay at 3–15% gap, RVOL > 10%, upside
      ≥ 5.5%.
- [x] **First weeks of live observation** — ✅ **CLOSED (21 August 2026).** Seven live
      sessions, 13–21 August (the cron was promoted at 20:14 CEST on the 12th, after that
      morning's window, so the 13th is the first session whose alerts persisted). **207
      alerts, 61 confirmed at 09:25, 5,900 Stage-1 evaluations, zero failed scans.**

      **The pipeline is sound, and the funnel proves its own bookkeeping.** 672 wake-ups
      across eight days: 0 failed, 0 stuck in `running`, 0 snapshot fetch errors. At the
      eight authoritative passes, 5,900 Stage-1 survivors resolve to 91 candidates and
      5,809 rejections — every ticker is either a candidate or carries exactly one recorded
      reason, with no remainder on any session. Profile coverage was **100%** every day
      (`with_profile` = `stage_1`), so `rvol_is_approximate` is false on all 207 alerts and
      the per-ticker fallback built in 4C has never fired in production. Universe 3,912–3,964,
      Stage-1 733–743, duration 65.9–67.7 s — the inputs are stable, so the alert count is
      the market talking.

      **The alert volume is smaller than 4C feared, and the fade is the bigger number.**
      Confirmed sets ran **3 to 14 (mean 8.7)**, not the 7–30 this item previously recorded
      — that range came from the observation sessions, and the 30 was Wednesday 12 August,
      a real pass, now the extreme of ten sessions rather than a typical morning. What no
      one had measured is that **only 21–42% of a session's alerts survive to 09:25**:
      14–41 tickers qualify at some point, 3–14 remain. The confirmed/faded split shipped
      on 15 August is therefore hiding about seven rows in ten, which is most of what makes
      the dashboard readable.

      **The ranking discriminates — least when it matters most.** Within a session the
      confirmed scores span ~0.3–0.5 (sd 0.108–0.184), so the ordering is real and not
      noise. But the top score is pinned at **0.893–0.924 across all seven sessions**,
      covering a 3-candidate Tuesday and a 14-candidate Friday alike: the saturation design
      guarantees a ~0.90 leader every morning, so **the score has no cross-day meaning** and
      the UI presents it as a bare number. Worse, the head of the list compresses as the
      list grows — top-minus-rank-5 was 0.206 at 8 candidates, 0.140 at 11, **0.074 at 14**.
      Exactly when the user most needs the ranking to choose for him, it separates least.
      The mechanism is measured, not guessed (weight × observed sd):

      | factor | weight | sd | share of the spread |
      |---|---:|---:|---:|
      | rvol | 30% | 0.324 | 37.6% |
      | upside_headroom | 25% | 0.362 | 35.0% |
      | liquidity | 15% | 0.274 | 15.9% |
      | gap_position | 20% | 0.148 | 11.4% |
      | data_quality | 10% | **0.000** | **0.0%** |

      `data_quality` is **1.000 on all 61 confirmed alerts** — a constant +0.100 that cannot
      move any ranking. It was built for V1 conditions (demo profile, approximate RVOL,
      fixture snapshots) and on Premium with full profile coverage its penalties never
      apply. `gap_position` carries a fifth of the weight for a ninth of the discrimination.
      Both are inputs to Phase 5's weight fitting, which no longer starts from a blank
      slate.

      **Three findings handed forward rather than acted on** — see Phase 5:
      1. **The RVOL floor is nearly inert as a filter.** Stages short-circuit gap-first, so
         `rvol_pct > 10` is only ever asked about tickers that already gapped 3–15%, and it
         then rejects **47 of 307 (15.3%)**. Normalized RVOL still earns its keep — it is
         the largest single driver of the *ranking* — but as a gate it barely binds.
      2. **The breakout convention now has the frequency §4.3 deferred it for.**
         "No resistance above price" fired **46 times in 8 sessions — 17.7% of Stage-2
         survivors, ~5.75 a morning.** Nearly one in five momentum survivors is discarded
         as unmeasurable headroom. Still a strategy call for the end user; it now has a
         number attached. (It is also why `upside_pct IS NULL` never occurs: these are
         rejected, never alerted, so the nullable columns stay unexercised in production.)
      3. **The scanner surfaces fresh names, not a recurring cluster.** 61 confirmed alerts
         came from **55 distinct tickers**, 6 of which repeated and none three times — out
         of a stable ~740-ticker Stage-1 pool.

      **One analysis trap found, no production impact.** `clock.is_final_pass()` is
      `at_minute(now) >= 09:25`, and the `scan_runs` row opens *before* the window gate, so
      every post-window heartbeat — 18 a day — is stamped `is_final_pass: true`. Nothing
      reads it there (`/status` selects `last_run` with `status != 'skipped'`, and
      `alerts.is_final_pass` is a separate column that cross-checks perfectly against
      `risk_filters` on all eight sessions), but a `scan_runs` query written the obvious way
      returns 19 rows a day instead of 1. Phase 5 queries this table for a living. Filter on
      `status = 'completed'` as well, or guard the write. Same family as the session-total
      hotfix: a field that is true for a reason the reader does not expect.
- [x] **Tier the early cadence** — ✅ **DONE (17 August 2026).** 19 passes a session rather
      than 66: 04:15 → hourly → 07:00 → 30 min → 08:00 → 15 min → 08:30 → 5 min → 09:25,
      config-driven via `SCAN_CADENCE_TIERS`, gated in `services/scanner/cadence.py`. The
      shape is measured (6 sessions, 394 passes, `scripts/cadence_profile.py`): candidate
      *yield* is flat from 04:15 to 08:40, so the original "early passes are uninformative"
      argument was wrong; *churn* is the deciding number, and the 32 passes from 04:25 to
      06:55 produce 1.4 confirmed-relevant first sightings a session between them against a
      73% keep rate in the last 40 minutes. Safe because scans are stateless — pinned by a
      test that runs the 09:25 pass under a one-pass cadence and the old 5-minute one and
      asserts an identical candidate set. The slot list always ends at 09:25, so no config
      value can silence the authoritative pass. Cost: Phase 5 loses the transients that both
      appear and vanish inside a coarse gap; all four observation anchors (04:15, 07:00,
      08:30, 09:25) survive.
      > **The bandwidth premise did not survive measurement, and that is the finding.**
      > Per-pass `bytes_used` says the live session costs **48.5 MB at 66 passes and 22.6 MB
      > at 19** — ~2.0% of the 50 GB / 30-day allowance before, ~0.9% after. The "~47% of
      > allowance" figure below was a projection from 4C's 10.2 MB `--at` replay pass, and an
      > `--at` replay of a *past* session returns the whole extended day (~190 bars/ticker)
      > rather than the ~65 a live 09:25 pass carries. The cadence still earns its place on
      > information grounds; it was never the bandwidth emergency 4C described. Note also
      > that the saving is **53%, not the 71% the pass count suggests** — the passes kept are
      > the late, expensive ones. Confirmed 18 August with the calls column: **737 calls a
      > pass against 4C's 672**, so the universe grew ~10% and the gap is payload alone.
      >
      > **Confirmed against four sessions of the cadence actually running** (21 August, from
      > `scan_runs` summed per ET session date). The re-sum was sound and slightly
      > conservative: **46.3 MB at 66 passes (17 Aug) against 20.6 MB at 19 (18–21 Aug,
      > range 20.1–21.4), a 55% cut.** The first tiered session was **18 August** — the
      > commit landed at 19:55 CEST on the 17th, after that morning's window. Call counts
      > land exactly where predicted too: 48,642/day before (737.0 per pass, identical on
      > every pass, since the fan-out is one call per Stage-1 survivor and that set is fixed
      > for the session) against ~14,000 after. That mattered more than anyone noticed —
      > the old cadence peaked at **56,011 calls against the shared 80,000 ceiling, 70%**,
      > where a single `--rebuild` night would have breached it. It is now 24%.
- [x] **Open the scan window at 04:15, not 04:00** — ✅ **DONE (17 August 2026),** shipped
      ahead of the tiering as its own commit. The 04:00, 04:05 and 04:10 passes produced
      zero candidates in 18 of 18 session-passes, structurally — with the ~7-minute settling
      window the 04:00 bar is not trusted until ~04:12, so those passes cannot produce one.
      The window start and the volume-profile bucket epoch were the same constant and are
      now deliberately separate: `premarket_volume_profile` is keyed on minutes since 04:00
      and holds stored rows, so a shared constant would have rebased every RVOL denominator
      lookup by three buckets with no error. A test pins it.
- [x] **Make the volume-profile build incremental across days** — ✅ **DONE (16 August
      2026).** A fresh night now costs **one request per ticker** (0 on a same-day re-run,
      full pagination on `--rebuild`), against ~2,776 calls and ~140 MB for the old nightly
      rebuild — roughly a 73% cut, to ~741 calls and ~37 MB.
      **Byte figures now measured (21 August 2026): the whole nightly cycle went 437.9 MB →
      ~245 MB, a 44% cut**, nearly double the ~103 MB the brief predicted for the profile
      job alone. `api_budget` cannot say which job the extra saving came from — see the
      attribution note in Phase 4B. The first post-deploy night still paid full price
      (Mon 17 Aug), because `premarket_session_volume` was empty until its first run and had
      to be populated by full pagination; **17→18 August was the first genuinely incremental
      night**, and the drop is visible as a single step in the daily byte series.
      Required a table the brief did not anticipate: `premarket_session_volume` keeps the
      per-session curves, because "drop the oldest" cannot be done on a per-bucket average
      whose contributions were never stored. That table also retains the RVOL denominator's
      inputs, closing one of the three reasons a past session cannot be replayed.
      An incrementally-updated profile is asserted identical to a full rebuild of the same
      window — RVOL divides by this, so a discrepancy would be silent.
- [x] **Persist candidate detail, not just tickers** — ✅ **DONE (16 August 2026).**
      `scan_observations` records every Stage-1 survivor at the 09:25 pass and candidates at
      three anchors, with the reference denominators copied onto each row. The threshold
      sweep is pinned by a test that replays Stage 2 at a different RVOL floor from stored
      rows alone. Measured cost: 225 ms for 741 rows, on 1 pass in 66. Retention indefinite.
      One limit, explicit and tested: stages short-circuit, so a gap-rejected ticker has no
      RVOL and a gap sweep reports it unresolved rather than passing. Original brief below. `stage_counts_json` stores candidates
      as plain ticker strings and rejections as `{ticker, stage, reason}` with no values, so
      the scanner records *that* a ticker was rejected at Stage 2 and never *what its gap and
      RVOL were*. Phase 5's **threshold sensitivity sweep** — the commitment to justify or
      revise 3% / 15% / 10% / 5.5% — therefore cannot be asked of the stored data at all, at
      any cadence.
      Unfixable in hindsight: 49.4% of pre-market bars revise upward within ~7 minutes, and
      both denominators are overwritten nightly (`reference_data` is one current row per
      ticker; `premarket_volume_profile` is unique per `(ticker, bucket_minute)`). Every
      session that runs without this is evidence gone for good — which is exactly why it
      outranks a bandwidth optimisation. Sized at ~21 MB/year: Stage-1 survivors at the
      09:25 pass, candidates at three earlier anchors.

---

### Pre-Phase 5 — the four things between here and backtesting

**Renumbered 22 August 2026.** Backtesting was Phase 6 and is now **Phase 5**; hardening
was Phase 7 and is now **Phase 6**. The old Phase 5 (enrichment) is not a phase any more:
its one item with a slot already waiting in the product — catalyst tagging — is pulled
forward to the list below, and the rest becomes an explicit backlog at the end of this
file rather than a numbered phase nobody had scheduled.

**Why anything comes before Phase 5 at all:** backtesting is *time-gated*. It needs ~20
sessions to sweep credibly and ~40 to span different tapes, and full-evaluation evidence
only started accumulating on 24 August. These four fill that wait, in this order.

- [ ] **1. Verify Follow-up D on the first live session** (Mon 24 August, after 15:25 CEST).
      `backend/scripts/sql/followup_d_verify.sql`. The sharp check is **V2**:
      `stage_1 = candidates + rejections` with a remainder of **zero**, the identity that
      held on all eight sessions of the Phase 4 close. A non-zero remainder means an
      evaluated ticker re-labelled its own rejection, which is the one hazard the
      Follow-up D brief got right. V3 confirms the point of the change (gap-rejected rows
      now carry RVOL); V4 confirms the promise it was sold on (`calls = stage_1 + 1`,
      duration flat at ~66 s).
- [ ] **2. Scan-failure alerting** — brief in `docs/PROMPT.md`. **The plan's own gate for
      this passed two weeks ago.** Phase 7 was scoped "before the end user relies on it",
      and he has opened the dashboard daily since 13 August. Today a failed scan is
      *recorded* and *displayed*, and nobody is *told* — it reaches a human only if that
      human looks, and it looks exactly like a quiet market. Zero failures in 672 wake-ups
      is a good record, not a guarantee.
- [ ] **3. Catalyst tagging** — the one enrichment item that is already a hole rather than
      an idea. `catalyst` is in the §4.4 alert contract, has a slot on the card, and was
      **null on all 207 alerts** of the observation window.
      > **Show it without scoring it.** Phase 4 measured the ranking as the product's weak
      > point, so wiring new signals into the confidence score is the tempting move and the
      > wrong one: it would add unfitted weights to a formula whose measured flaw is
      > unfitted weights, and enlarge Phase 5's fitting problem against the same data.
      > Catalyst earns weight in Phase 5, with outcomes to justify it, or not at all.
- [ ] **4. Delete the `SCAN_FULL_EVALUATION` flag** once a week of sessions confirms the
      candidate sets are unchanged — the setting, the `render.yaml` key, and the parameters
      threading it through `stages.py`. It was built as a rollback switch, not a rollout,
      and a permanent flag is a permanent second code path. The gate (a clean week) will
      most likely fall *during* item 3; it is a chore to slot in, not a phase to schedule.

---

### Phase 5 (V3) — Backtesting & Calibration
*(was Phase 6)*
No new subscription — same Premium key, deeper work. Historical replay harness over stored
`scan_runs` (**not** re-fetched history, which has since settled upward — that is what the
alert-provenance fields exist for); outcome labelling (did it reach +5% within the first
hour?); per-signal hit rates; fitted confidence weights replacing the provisional ones;
threshold sensitivity sweep to justify or revise 3% / 15% / 10% / 5.5%; results published in
the dashboard.

> Until this completes, the confidence score is a documented assumption, not a model, and
> the UI says so.

**What Phase 4's observation window hands to this phase** (21 August 2026, 7 live sessions):

> **The sweep can answer for two of its four thresholds, not all four.** Stages
> short-circuit, and at the eight authoritative passes **94.7% of everything gap-tested was
> rejected on gap** (5,431 of 5,738) — with no RVOL and no upside recorded, because they
> were never computed. `sweep_limitations()` would correctly report almost the entire
> population as unresolved for a **widened gap band**. Only 307 tickers ever reached the
> RVOL test and 260 reached Stage 3, so **the 10% and 5.5% floors are fully answerable from
> stored rows, while 3% and 15% are not.**

> **Prerequisite — ✅ SHIPPED 22 August 2026, Follow-up D** (`docs/PROMPT.md`). Every
> Stage-1 survivor now carries gap, RVOL and headroom whatever rejected it, so the widened
> gap band is answerable from stored rows. Costs no API calls and no queries: the fan-out
> already covers every Stage-1 ticker (`api_calls_used` = `stage_1` + 1) and the profile
> map is already bulk-loaded (`with_profile` = `stage_1`). The candidate set cannot move,
> structurally — both evaluation passes run after their stage has finished deciding and
> append neither survivors nor rejections — and a test pins it.
>
> **The sweep still has one honest limit, and one date to respect.** Tickers with no
> pre-market snapshot (~20 a session) have no values at all and must come back unresolved;
> `sweep_limitations()` was narrowed rather than deleted. And **rows written before
> 22 August 2026 carry the old short-circuit NULLs** — the seven sessions of Phase 4's
> observation window among them — so a sweep spanning that boundary must split on session
> date rather than treating the population as uniform.

- **Start the weight fitting from the measured factor table**, not from the priors.
  `data_quality` is a **constant 1.000** on every live alert (a +0.100 offset that cannot
  rank anything), `gap_position` carries 20% of the weight for 11% of the discrimination,
  and RVOL + upside drive 73% of it. See the table in Phase 4's observation close.
- **Test raising `SCAN_RVOL_MIN` first.** As a filter it currently rejects **47 of 307
  (15.3%)** of the tickers that clear the gap band — nearly inert — while being the single
  largest driver of the ranking. This is the threshold with the most obvious room to move
  and the one the stored data can actually adjudicate.
- **Two ranking defects to fit against, not just hit rates.** The top score is pinned in a
  0.031 band across sessions (no cross-day meaning), and the head of the list compresses as
  the list grows. A fit that improves hit rate but leaves ranks 1–5 inside 0.074 on a
  14-candidate morning has not solved the user's problem.
- **Query `scan_runs` with `status = 'completed'`.** `is_final_pass` is stamped on every
  post-window heartbeat too — 18 a day. See the note in Phase 4.
- Evidence is accumulating as designed: **3,781 `scan_observations` rows over 19 runs**
  (17–21 Aug), every Stage-1 survivor at each final pass plus ~6.4 candidates per anchor.

### Phase 6 — Hardening
*(was Phase 7)*

Its old subtitle was "before the end user relies on it". **That gate passed on 13 August**,
when alerts began persisting and he started opening the dashboard daily, so the phase is
no longer speculative and its most urgent item has been pulled into Pre-Phase 5. What
remains:

- **Auth on the dashboard.** Currently unauthenticated and reachable by URL — open item #6
  in `docs/CLAUDE.md` §10, "deferred by decision, but revisit before wider sharing".
- **Push/email delivery at 09:25 ET.** Note this is a *different audience* from the failure
  alerting in Pre-Phase 5: candidates go to the end user, operational failures go to the
  operator. Building the first should reuse the transport the second establishes, and must
  not reuse its recipient.
- **FMP usage and bandwidth monitoring.** Partly free once failure alerting exists — see
  the brief's note that `FMP_BANDWIDTH_WARN_PCT` is already computed and today reaches a
  human only if that human runs a CLI script.
- ~~Scan-failure alerting~~ — **moved to Pre-Phase 5 item 2.**

---

### Backlog — enrichment (formerly Phase 5)

Not a numbered phase any more: it was never scheduled, and catalyst tagging — the only
part with a slot already waiting in the product — is now Pre-Phase 5 item 3. What is left
here is genuinely optional, and each item should have to argue for itself against the
measured weakness of the moment rather than inherit a place on the roadmap:

- Sector relative strength
- Bid-ask spread
- Short interest (a slow signal — FINRA reports ~2×/month)
- Halt-risk flag
- Gap-and-go history

> **Anything from this list that becomes a scoring factor lands after Phase 5, not before.**
> The same argument that keeps catalyst out of the confidence score applies to all of them:
> Phase 4 measured the ranking's flaw as *unfitted weights*, and adding more unfitted
> weights before the fitting happens makes that worse while enlarging the fit.

---

## Sequencing rules

1. CI never touches live FMP. Fixtures always.
2. One phase per Claude Code session; verify "done when" before advancing.
3. Probe before building. Every FMP and Tiingo capability claim taken on trust in this
   project has needed correction roughly half the time — see
   `docs/TIINGO_VS_FMP_EVALUATION.md` §11 for the five that failed.
4. Every schema change: reversible migration, RLS on new tables (CI enforces it), and a
   round-trip test on **populated** data. Empty-database round-tripping is how the
   downgrade bug shipped.
5. `pg_dump` before running any downgrade against a real database.
6. Measurements are reported with their conditions. A same-day re-run is not an incremental
   nightly build; a hypothesis that fits the data is not a tested hypothesis.

---

## Known risks

| Risk | Impact | Mitigation |
|---|---|---|
| ~~Split-distorted reference data~~ **DISPROVED** | — | `historical-price-eod/full` is already split-adjusted (verified: price and volume ratios both exactly 150.0 against the non-split-adjusted series). The flagged tickers were real collapses, not data errors |
| ~~Extreme-upside candidates from collapsed stocks~~ **CONTAINED** | A stock down 85% has all historical levels far above it → huge upside → could outrank genuine setups | **Three independent barriers.** (1) `price_regime_break` (3×) and `scan_upside_max` (100%) reject the extremes as named risk-filter rejections. (2) The confidence score's upside factor **saturates at 16.5%** (5.5 × 3.0), so extra headroom buys no ranking advantage — and the dashboard sorts by confidence. (3) `score_data_quality` penalises unmeasured headroom. Verified live 11 Aug: all candidates 1.7–13.5% upside, no collapsed names in the list |
| **Confidence ranking is unvalidated** — *and now measured to be weakest exactly where it is needed* | The weights are reasoned assumptions, not fitted. Seven live sessions add two specifics: the top score is pinned at 0.893–0.924 regardless of market conditions, so it carries **no cross-day meaning**; and the head of the list **compresses as the list grows** (top-minus-rank-5 was 0.206 at 8 candidates, 0.074 at 14) | Labelled provisional in API and UI; every score exposes its full factor breakdown so the *why* is inspectable. Only Phase 5 backtesting retires `is_provisional` — and it now starts from the measured factor table in Phase 4, not from scratch |
| Bandwidth growth with universe size | **The scan was never the problem, and 4B's monthly figure hid the one that is.** The live scan is 20.6 MB/session, 0.45 GB/month, **0.9%** of the 50 GB allowance. The **nightly job is ~92% of all consumption** — its cost was recorded as "1.1% of the allowance" by stating one night's 453 MB as a 30-day total (see Phase 4B). Measured total draw: **20.8% of allowance before the 18 August optimisations, 11.4% after** | Tiered cadence (53→55% off the scan); incremental nightly profile build (44% off the nightly, measured 21 Aug); bandwidth tracking in the guard; 400-day EOD bound. Headroom is ample either way — but any future bandwidth work belongs on the nightly refresh, not the scan |
| Render cron UTC/DST drift | Wrong-hour scans twice a year | Explicit ET conversion, generous UTC schedule + ET gate, DST tests. **Also:** boundary comparisons are minute-resolution, so scheduler latency cannot push a scheduled pass outside its own window — that bug silently cost the authoritative 09:25 pass for three sessions |
| Silent scan failure | Looks like a quiet market | `scan_runs` failure taxonomy + distinct UI states + failure alerting (Pre-Phase 5) |
| Demo profile confused for production | Misleading alerts | Profile name stamped on every scan run and alert; demo output badged in the UI |
| Supabase RLS on public tables | Without RLS, anyone with the project URL + anon key can read/write via the auto-generated Data API | RLS enabled with **no policies** on every public table — denies the Data API, leaves the app unaffected (backend connects as `postgres`, which bypasses RLS). A CI test fails if any table lacks it |
| Over-trusting the confidence score | User treats provisional weights as validated | Labelled provisional in API and UI until Phase 5 |
| **Alert volume variance** | **Smaller than feared, and re-measured.** Seven live sessions confirmed **3–14 candidates (mean 8.7)** at the authoritative pass — the 7–30 range came from the observation sessions and 30 remains the worst case of ten, not a typical morning. The real number nobody had: **only 21–42% of a session's alerts survive to 09:25**, so 14–41 tickers qualify and 3–14 remain | Not a fault — it tracks real market conditions. The confirmed/faded split carries it: it demotes roughly seven rows in ten, which is most of what keeps the dashboard readable. The burden still falls on the confidence ranking, and a busy morning still yields the longest list with the *least* separated head — see the row above |

---

## Legacy notes

- `backup.sql` moved out of the repo; `*.sql` gitignored; never restore into Supabase.
- Alpaca, the v1 rule engine and the MCP server were removed in Phase 3.5 (three separate
  commits, 29 July 2026).
- Starter was never purchased — V1 (free) → V2 (Premium). Any reference to a Starter
  subscription in older sections is historical.
- Migrations are the highest-risk surface in this project: two production incidents in three
  phases (pgBouncer prepared statements, and a downgrade that failed on populated data).
