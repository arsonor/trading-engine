# Claude Code Prompts — Trading Engine v2 (tier-staged delivery)

Run in order, one per session. Verify each phase's Definition of done before advancing.
Reference: `docs/CLAUDE.md` (spec), `docs/PLAN.md` (roadmap + version ladder),
`docs/PROJECT_REPORT.md` (V1→V4 tiers).

- **Phase 0 — Infrastructure: ✅ DONE** (Postgres everywhere, Render Frankfurt web +
  cron stub, Vercel, Supabase, CI trimmed, connectivity verified). Prompt removed;
  see git history if needed.
- Phases 1–3 build **app V1 on the free FMP tier** — no subscription required.
- Phase 4+ is **V2 on FMP Premium** (purchased 5 Aug 2026). Starter was skipped: it has
  no pre-market volume source, and pre-market volume is non-negotiable for the end user.
  `extended=true` (Premium) is the reason for the purchase and the subject of Phase 4A.

---

## Phase 1 (V1) — FMP client, API budget guard, reference-data pipeline

**Status:** ✅ DONE (25 July 2026)
**Tier:** FMP Basic (free) — 250 calls/day hard cap, EOD data only, 43 accessible symbols

See Git history for details

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

See Git history for details

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

See Git history for details

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

See Git history for details

---

## Phase 4-prep (free tier) — Enforce Row-Level Security on every table

**Status:** ✅ DONE (2 August 2026) — migration `dbdf5784db31` enables RLS on all eight
`public` tables with zero policies; `tests/integration/test_rls.py` fails (never skips)
when any `public` table lacks it. Policy lives in `app/core/rls.py`; the convention is
documented in `alembic/script.py.mako` and `alembic/README`, where the next migration
author will actually meet it.
**Depends on:** Phase 3.5
**Tier:** free — no subscription needed. Good use of the wait on FMP support.

See Git history for details

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

See Git history for details

---

## Phase 4A-T — Tiingo free-tier empirical probe (optional, runs before or beside 4A)

**Status:** ✅ DONE
**Depends on:** Phase 4-prep
**Tier:** Tiingo **free** account — costs nothing
**Purpose:** settle by measurement whether Tiingo's consolidated Equity Realtime endpoint
could serve this scanner's live half. Background and the full comparison are in
`docs/TIINGO_VS_FMP_EVALUATION.md`.

> **This is a measurement exercise, not an integration.** The recommendation remains FMP
> Premium. This probe exists because Tiingo's `/tiingo/equity/intraday` snapshot returns
> the whole market's consolidated pre-market volume in a **single request**, which would
> be architecturally better than anything FMP offers for live scanning — if it works for
> low-float small caps and leaves beta. An hour of measurement now makes that a decision
> rather than a guess.

See Git history for details
---

## Phase 4A (V2) — FMP **Premium** capability probe

**Status:** ✅ DONE — **run during a live pre-market session** (04:00–09:30 ET = 10:00–15:30 CEST)
**Tier:** Premium, active since 5 Aug 2026 (month-to-month). Key already in `backend/.env`.
**Writes no product code.**

> Starter was skipped: it has no pre-market volume source, and the end user declared
> pre-market volume non-negotiable. Premium's `extended=true` is the reason for the
> purchase — and it is the one claim in this project that has never been measured.

````
# Phase 4A — Measure what FMP Premium actually delivers

## Context
Read `docs/PLAN.md` ("Delivery model" + Phase 4A) and `docs/TIINGO_PROBE_FINDINGS.md`
first. The latter is the model for this phase: same discipline, different provider.

The FMP key in `backend/.env` is now **Premium** (purchased 5 Aug 2026, month-to-month).
FMP support states that `extended=true` adds pre-market and after-market intervals to
intraday charts, works for any US symbol with intraday data regardless of float or market
cap, and that Premium also unlocks `batch-quote`, 1-minute bars, 750 calls/min, 30 years of
history and no daily request cap (50 GB per rolling 30 days).

**None of that is measured.** In this project, roughly half of what a vendor asserted has
needed correction once probed — five separate claims in the Tiingo evaluation alone. This
phase measures before Phase 4B builds.

This phase writes **no product code**: a probe script, recorded fixtures, and a findings
document. Do not modify the scanner, alerts, dashboard, or the existing FMP client beyond
what is needed to call new endpoints.

## Questions to answer

**A. `extended=true` — the decisive test**
1. Call `historical-chart/5min?symbol=X&from=...&to=...&extended=true` during a live
   pre-market session. Does it return pre-market bars at all? Capture full raw payloads.
2. **What time does the earliest bar of the session start** — 04:00 ET, or later? The
   scanner's window opens at 04:00; if bars begin at 07:00 or 08:00 the timing model in
   `docs/CLAUDE.md` §4.5 must change.
3. **Is `volume` per-bar (summable) or already cumulative?** This determines whether
   `volume_premarket_accumulated` is a sum over bars or a direct read. Establish it by
   comparing consecutive bars against their own magnitudes — state the evidence, do not
   infer from field naming.
4. **Does it work for genuinely low-float small caps?** This is the case that matters and
   the one a megacap-only test would flatter. Build the test set from **real floats**:
   use `shares-float-all` (or `shares-float`) to find at least 15 US common stocks with
   float < 75M and price > $2, then probe those. Report a **per-ticker table**, not an
   average — an average hides the failure that matters.
5. What is returned for a ticker with **no pre-market activity** — empty array, zero-volume
   bars, or stale bars from a previous session? The scanner must distinguish "not trading"
   from "no data", and a stale non-null value is the dangerous case.
6. Do 1-minute bars also support `extended=true`, and how do they compare to 5-minute?

**B. Data-integrity guard — learn from the Tiingo probe**
7. The Tiingo probe found a low-float ticker whose cumulative volume **reset to zero
   mid-session and re-accumulated from a new baseline**, permanently losing the earlier
   total. Every row looked healthy in isolation. For RVOL that is the worst failure shape:
   a plausible small number that silently drops a real candidate.
   **Do not assume FMP is immune.** Sample the same tickers repeatedly across the session
   and check whether any cumulative series decreases, or whether re-requesting the same
   historical window returns different volumes. Report explicitly either way.

**C. History depth — gates volume profiles and V3 backtesting**
8. **How many days of extended-hours intraday history are available?** The advertised "30
   years" refers to daily bars. ≥20 sessions are required for `premarket_volume_profile`;
   V3 backtesting needs far more. Probe backwards until data stops and report the real
   limit, plus any per-request row cap.
9. Is pre-market history complete for low-float names, or sparse/missing on quiet days?

**D. Scale endpoints**
10. `batch-quote` — confirm it is no longer 402. Max symbols per request? Payload size?
    Does it include pre-market prices during the pre-market window, or regular-hours only?
11. `shares-float-all` — record count, payload size, pagination, small-cap coverage,
    and how current the data is.
12. `company-screener` — exact fields returned, pagination, which filters are honoured.
    **Measure universe size at 3+ pre-filter settings** (e.g. `price > 2 AND volume >
    500000` with market-cap ceilings of $2B / $5B / none). 4B needs these counts to size
    the nightly job. Note how over-inclusive each setting is, since market cap is only a
    proxy for float.
13. Re-check the **§6.1 contradiction**: FMP support says free-tier `shares-float` is
    limited to ~87 symbols, but the Tiingo probe measured 64/70 arbitrary small caps
    returning real floats on the free key. Irrelevant to Premium operationally, but it
    indicates vendor statements about tier limits are unreliable — note whether Premium
    behaves as documented.

**E. Limits**
14. Confirm 750/min and the absence of a daily cap. Do not deliberately exhaust anything.
15. **Measure payload sizes for every endpoint the scanner will use, and project monthly
    bandwidth** for a realistic universe and scan cadence against the 50 GB/30-day limit.
    Bandwidth, not call count, is the binding constraint.

## Scope

1. **`scripts/probe_fmp_premium.py`** — self-contained. Modes for each question group, and
   a `--sample-series --minutes N --interval M` mode for B.7. Re-runnable at different
   times of day. Raw responses written to `probe_output/fmp_premium/` (gitignored).
2. **All calls go through the existing budget guard.** Raise `FMP_DAILY_BUDGET` to a
   Premium-appropriate value via config — do NOT bypass or remove the guard. Its role
   changes from avoiding a hard 250/day stop to observability and runaway protection.
   Consider whether it should also track bytes; propose rather than implement if it grows
   the scope.
3. **Record fixtures** for every new endpoint shape via the existing recorder:
   `extended=true` bars (active and quiet tickers), `batch-quote`, `shares-float-all`,
   `company-screener` page. CI must stay offline.
4. **Extend the FMP client only as far as probing requires** — typed models and the same
   error taxonomy for new endpoints. No scanner or pipeline changes.
5. **`docs/FMP_PREMIUM_FINDINGS.md`** — every question above with the measured answer, raw
   evidence (including the per-ticker table from A.4 and any series from B.7), and an
   explicit list of what could NOT be determined and why.

## Constraints
- No changes to scanner logic, alert contract, thresholds, or dashboard.
- Do NOT run anything against the production Supabase instance.
- A.1–A.5 and B.7 **require a live pre-market session**. If run outside 04:00–09:30 ET,
  say so explicitly in the findings rather than inferring — an after-hours sample answers a
  different question.
- Persist raw payloads before analysing them. In the Tiingo probe, a timestamp-parsing bug
  produced a false negative that was only recoverable because the raw data had been kept.
- Report honestly what could not be measured.

## Definition of done
1. `scripts/probe_fmp_premium.py` runs and answers A–E as far as the session allows
2. `docs/FMP_PREMIUM_FINDINGS.md` exists with measured answers and raw evidence
3. **A verdict on the central question:** can V2 compute cumulative pre-market volume from
   `extended=true`, from what session start, and for low-float small caps? Yes/no, stated
   plainly, with the per-ticker table as evidence
4. **A verdict on normalized RVOL:** is ≥20 sessions of extended-hours history available,
   so `premarket_volume_profile` can be built?
5. B.7 answered — any evidence of volume resets or non-reproducible historical volumes
6. Universe counts at ≥3 pre-filter settings, and a projected monthly bandwidth figure
7. Fixtures recorded; tests pass offline; ruff clean; no production code changed
8. Report closes with: which Phase 4B/4C designs are confirmed, which must change, and any
   newly discovered constraint
````

---

## Phase 4B (V2) — Universe expansion + nightly refresh at scale

**Status:** ✅ DONE
**Depends on:** Phase 4A (measured — `docs/FMP_PREMIUM_FINDINGS.md`)
**Tier:** Premium, active. No live pre-market session required — this phase is nightly-job
work and can be built and run at any hour.

````
# Phase 4B — Real universe, nightly reference refresh, pre-market volume profiles

## Context
Read `docs/FMP_PREMIUM_FINDINGS.md` FIRST — it is measured, and it supersedes any
assumption in `docs/PLAN.md` or `docs/CLAUDE.md` about what FMP provides. Then read
`docs/CLAUDE.md` §4–5 for the specification.

App V1 is complete and deployed: FMP client, budget guard, 3-stage scanner, confidence
scoring, alerts and dashboard all work — but against a 43-symbol megacap universe on
free-tier EOD data, so the production profile correctly finds nothing. Phase 4A confirmed
Premium delivers everything the real scanner needs.

This phase replaces the toy universe with the real one and builds the data the live
scanner will consume. It does **not** touch the live scan path — that is Phase 4C.

## Measured facts from 4A that constrain this phase

| Fact | Consequence here |
|---|---|
| `shares-float-all`: 5,000 rows/page, 8 pages, ~5.2 MB, ~7 s → 19,569 US symbols with float | Nightly float refresh is ~8 calls, not N |
| 11,504 US symbols have float < 75M | Float alone is not a useful filter — the screener pre-filter does the real narrowing |
| `company-screener` returns 15 fields, **no float**, and honours price/volume/marketCap/exchange/isEtf/isFund | Two-step build is mandatory |
| Screener (US, price > $2, vol > 500K) = 1,880 rows, 693 KB | The pre-filter input size |
| **Stage-1 universe = screener ∩ float < 75M = 554 tickers** | Sizing reference — but see "do not hardcode" below |
| `historical-chart/5min?extended=true` returns pre-market bars from exactly 04:00 ET, back to at least 2016 | Volume profiles are buildable |
| Per-request row cap observed between 950 and 1,936 bars; ≤ 1 week at 5-min was reliable | Profile building must paginate by week, not request 20 sessions at once |
| Bar volume is **per-bar**, not cumulative | Cumulative volume is a **sum**, never a field read |
| **89 of 180 bars revised upward; all settle within 7 minutes of bar close** | Profiles must be built from **settled** bars only |
| No daily call cap; 750/min; 50 GB / 30 days | Bandwidth is the limit, not call count |

## Scope

### 1. Universe build — two-step, over-inclusive then exact

`scripts/build_universe.py` (or extend the existing refresh CLI — justify the choice):

1. **Screener pre-filter** — `company-screener` with US exchanges, `price > price_floor`,
   `volume > avg_volume_min`, `isEtf=false`, `isFund=false`, `isActivelyTrading=true`.
   Paginate fully. **Err toward inclusion**: the screener cannot see float, so anything it
   wrongly excludes is never seen again by any later stage. Filter values come from config,
   not literals.
2. **Bulk float** — `shares-float-all`, all 8 pages, into a float lookup.
3. **Join and apply the exact cap locally in SQL** — `float < 75M` is applied to
   `reference_data`, never to the screener request.
4. Upsert into `universe`. Mark symbols that disappear as inactive rather than deleting
   them — a delisted ticker still has alert history pointing at it.

**Do NOT hardcode 554.** That is one day's measurement of a filter's output, not a fixed
roster: it moves with price, 20-day volume, float changes, listings and delistings, and it
moves immediately if the end user edits thresholds. The job discovers the count each night.

**Record the count in `scan_runs` (or a small `universe_runs` record) and warn when it moves
materially** — e.g. more than ±50% from the trailing median, or above a configured ceiling.
4A measured that bandwidth becomes a real constraint past roughly 3,500 tickers, and a
threshold edit could cross that silently. A settings change must not be able to make scans
too slow to finish inside the 5-minute cadence without anyone noticing.

### 2. Nightly reference-data refresh at real scale

Extend `scripts/refresh_reference_data.py` to the real universe:

- Per surviving ticker: `historical-price-eod/full` → compute `volume_avg_20d`,
  `price_close_yesterday`, `high_yesterday`, `high_20d`, `sma_50`, `sma_200`. Float comes
  from the bulk call, **not** one `shares-float` per ticker.
- Budget- and **bandwidth**-aware, idempotent, resumable — preserve the existing semantics
  (skip tickers already refreshed today unless `--force`; a partial failure must not corrupt
  rows).
- Report calls used, bytes transferred, wall time, and per-stage counts.

### 3. Pre-market volume profiles — the new capability

Populate `premarket_volume_profile` (table exists, schema only, empty since Phase 1).

- For each Stage-1 ticker, fetch `historical-chart/5min?extended=true` over the last ~20
  trading sessions, **paginated by week** (the per-request row cap truncates longer ranges —
  4A measured truncation between 950 and 1,936 bars).
- For each session, take only pre-market bars (04:00 → 09:30 ET) and compute the **cumulative**
  volume at each 5-minute bucket — remember volume is per-bar, so this is a running sum.
- Average each bucket across sessions → `avg_cumulative_volume`, and store
  `sessions_sampled` so downstream code knows the profile's reliability.
- **Skip or flag tickers with insufficient history** rather than averaging noise. A profile
  built from 3 sessions must not be silently treated like one built from 20.
- Idempotent and incremental: a nightly re-run should add the newest session and drop the
  oldest, not rebuild 20 sessions per ticker every night. Report the incremental cost.

**The settled-bar rule — build this in from the start, do not retrofit it.**
4A measured that 49.4% of bars are revised upward after publication, all settling within 7
minutes of bar close. Profiles must therefore be built from **settled** bars only.
Historical bars from previous sessions are all settled, so this mostly matters for the
current session — but the rule belongs in one shared place because Phase 4C's live path
needs the identical definition.

Provide a single shared helper (e.g. `settled_bars(bars, now, exclusion_minutes)`) with the
exclusion window in **config, not hardcoded**. The 7-minute figure comes from one ordinary
session; a volatile or holiday-shortened morning could report later, and a hardcoded slice
would silently become wrong.

> **Why this matters beyond correctness:** in Phase 4C the live numerator and this profile
> denominator are divided by each other. If the profile is built from fully-revised history
> while the live sum includes provisional bars, RVOL is biased low by construction — the
> bias compounds and lands on the `rvol_pct > 10` gate. Both sides must use the same
> settled-bar definition and refer to the same clock time. Document this explicitly where
> the helper lives, because it is the kind of coupling that is invisible until alert counts
> come in mysteriously low.

### 4. Config and housekeeping

- Raise `FMP_DAILY_BUDGET` to a Premium-appropriate value; keep the guard — its role is now
  observability and runaway protection, not avoiding a hard cap.
- **Add bandwidth tracking** to the guard (bytes per day/month). 4A projects ~15% of the
  50 GB allowance at the current universe size; that is comfortable but it is now the
  binding limit and should be visible before it bites.
- Update `docs/CLAUDE.md` §6, which still documents `FMP_DAILY_BUDGET=230` — a free-tier
  value against a cap that no longer exists.
- Record fixtures for `company-screener` and `shares-float-all` pages, and for an
  `extended=true` multi-session window, so the profile builder is testable offline.

## Constraints
- **Do NOT touch the live scan path.** `FmpLiveSnapshotProvider`, `RVOL_MODE=normalized`,
  the cron wiring and the Render upgrade are all Phase 4C. This phase produces data.
- Do NOT change scanner stage logic, thresholds, the alert contract, or the dashboard.
- Do NOT run anything against the production Supabase instance.
- Any schema change needs a reversible migration, RLS on new tables (the CI test enforces
  it), and a round-trip test on **populated** data.
- CI stays offline — fixtures only.
- Mind the cost of a full profile build: ~554 tickers × ~4 weekly requests ≈ 2,200 calls.
  That is fine on Premium, but run it deliberately and report actual calls and bytes.

## Definition of done
1. `build_universe` produces a real Stage-1 universe from live Premium data; report the
   count, and confirm it is derived rather than hardcoded
2. Universe-size change detection works and warns on a large move or a configured ceiling
3. Nightly refresh populates `reference_data` for the full universe; report calls, bytes
   and wall time
4. Re-running the same day is idempotent (~0 additional calls)
5. `premarket_volume_profile` is populated for the Stage-1 universe with `sessions_sampled`
   recorded; tickers with thin history are flagged, not silently averaged
6. The settled-bar helper exists in one shared place, is config-driven, and is unit-tested
   including the boundary at the exclusion window
7. An incremental profile re-run costs materially less than a full rebuild — report both
8. Bandwidth tracking reports bytes; `docs/CLAUDE.md` §6 updated
9. Existing scanner output is unchanged: `run_scan.py --fixture --profile demo --at
   "<fixed time>"` produces identical results before and after
10. Tests pass offline; ruff clean; migrations round-trip on populated data
11. Report: real universe size, calls and bytes for a full nightly cycle, profile coverage
    (how many tickers got ≥20 sessions), and anything that blocks Phase 4C
````

---

## Phase 4C (V2) — Live scanning: real data, normalized RVOL, cron go-live

**Status:** ✅ DONE (7 August 2026) — delivered as four commits: live provider + normalized
RVOL, integrity guards + provenance, market tape, infrastructure.
**Depends on:** Phase 4B (universe + reference data + volume profiles populated)
**Tier:** Premium, active
**This is the phase that turned the scanner on.**

**Measured:** a full live pass runs in 60.2 s (672 calls, 10.2 MB) against a 5-minute
cadence, funnelling 3,948 → 671 → 62 → 30 → **30 candidates**.

**The cron is deliberately still on `--dry-run`** — stage 1 of the two-stage go-live. It
runs the full pipeline and records `scan_runs`, but persists and broadcasts nothing until
several sessions confirm the candidate count is sane. See `render.yaml` for how to promote.

**Four items carried forward** (detail in `docs/PLAN.md` Phase 4C): promote out of dry-run,
tier the early cadence (bandwidth measured at ~47% of allowance, not the ~15% projected),
make the profile build incremental across days, and decide what to do about
split-distorted reference data — currently flagged but not corrected.

````
# Phase 4C — Live snapshot provider, normalized RVOL, cron go-live

## Context
Read `docs/FMP_PREMIUM_FINDINGS.md` FIRST (measured; supersedes any assumption elsewhere),
then `docs/CLAUDE.md` §4 for the scanner spec and `docs/PLAN.md` Phase 4C.

Everything is now in place except the live path. V1 shipped the full pipeline, scoring,
alerts and dashboard. Phase 4B built the real universe (3,948 maintained, ~694 Stage-1
eligible), the nightly `reference_data` refresh, and `premarket_volume_profile` (691 tickers
with ≥20 sessions). Stage 2 still reads a fixture scenario.

This phase replaces that fixture with live FMP data and puts the scanner on a schedule.

## Measured facts that constrain the design

| Fact (from 4A/4B) | Consequence |
|---|---|
| `batch-quote` returns the **previous session's close** during pre-market | **Do not use it for the live snapshot.** Per-ticker `historical-chart/5min?extended=true` only |
| ~694 Stage-1 tickers × 750 calls/min ≈ **0.7 min per pass** | Per-ticker fan-out is affordable inside a 5-minute cadence |
| `extended=true` returns bars from **exactly 04:00 ET** | The `docs/CLAUDE.md` §4.5 timing model needs no change |
| Bar `volume` is **per-bar, not cumulative** | Accumulated pre-market volume is a **sum over bars** |
| Quiet tickers return an **empty array**, not stale bars | "Not trading" and "no data" are distinguishable by row count — no staleness heuristic needed |
| **49.4% of bars revised upward; all settle within 7 min of bar close** | The live sum must use `settled_bars()` — see the symmetry rule below |
| Nightly cycle = ~6,900 calls / 453 MB; 0.53 GB of 50 GB per 30 days | Live scanning adds roughly 694 × 66 passes ≈ 46k calls and ~90 MB/session. **Measure it; do not assume** |

## Scope

### 1. `FmpLiveSnapshotProvider`

Implement the `MarketSnapshot` provider interface defined in Phase 2 (`app/services/
scanner/snapshot.py`), alongside the existing fixture provider — selected by config, not by
replacing it. The fixture path must keep working: it is how the pipeline is tested offline.

For each Stage-1 candidate at scan time `T`:
- Fetch `historical-chart/5min?symbol=X&extended=true` for today.
- Filter to pre-market bars (04:00 ET → min(T, 09:30 ET)).
- Apply **`settled_bars()`** from `app/services/bars.py` (built in 4B).
- **Sum** the per-bar volumes → `volume_premarket_accumulated`.
- Take the last settled bar's close → `price_premarket_current`.
- An **empty array means the ticker has not traded yet** — a legitimate, expected state.
  It must produce a "no pre-market activity" outcome, never an error and never a zero that
  looks like measured stillness.

Concurrency: 694 sequential requests will not fit comfortably in the cadence. Use bounded
concurrency that respects 750/min, with the existing budget guard counting every call.
Degrade gracefully — a handful of failed tickers must not fail the scan; record them.

### 2. Normalized RVOL — and the symmetry rule

Switch `RVOL_MODE` to `normalized` and implement `NormalizedRvol` against
`premarket_volume_profile`: today's settled cumulative volume at time `T`, divided by the
profile's `avg_cumulative_volume` for the bucket at `T`, × 100.

**This is the highest-risk correctness item in the phase.** The profile denominator was
built from fully-revised historical bars. If the live numerator includes provisional bars,
RVOL is biased low **by construction**, landing directly on the `rvol_pct > 10` gate — and
the symptom is simply fewer alerts, with nothing indicating a fault.

Requirements:
- Both sides use the **same `settled_bars()` definition** and refer to the **same clock
  bucket**. If the live sum excludes the most recent N minutes, the profile lookup must use
  the correspondingly shifted bucket. Do not compare a settled numerator against an
  unshifted denominator.
- Write a test that pins this: a ticker whose live volume exactly matches its profile must
  score ~100% RVOL, at several times of day including near 09:25.
- Fallback when a ticker has no profile or `sessions_sampled` is below a configured
  minimum: use `SimpleRvol` and **flag the alert as using a degraded metric** (the
  `ApproxRvolBadge` already exists in the frontend). Never silently mix the two.

### 3. Data-integrity guards

4A found no volume resets on FMP, unlike the Tiingo probe — but absence of evidence from
one session is not a guarantee. Implement cheap guards:
- **Monotonicity check**: within a session, a ticker's accumulated volume must not decrease
  between passes. A decrease is a data fault — log it loudly, keep the previous higher
  value, and mark the ticker's RVOL as suspect for that session rather than acting on the
  lower number.
- **Sanity bounds**: reject or flag an accumulated volume that exceeds a configurable
  multiple of the ticker's `volume_avg_20d` (a 50× pre-market reading is more likely a data
  error than a real event).
- Record both in `scan_runs` so they are visible rather than buried in logs.

### 4. Market-tape check

Replace the V1 neutral stub with a real index/futures reading (e.g. SPY or an index quote
via FMP). Per `docs/CLAUDE.md` §4.3 this is a **risk filter** and a confidence input, not a
hard gate. If the tape cannot be read, the scan continues and records "tape not measured" —
exactly as V1 does now. Do not let an unavailable index abort a scan.

### 5. Alert provenance — needed for V3 backtesting

Record on each alert what the scanner actually saw at decision time:
- `bars_settled_through` (the effective cut-off timestamp)
- `provisional_bars_excluded` (count)
- `rvol_mode` used (`normalized` / `simple` fallback)
- `profile_sessions_sampled` for the ticker

Without this, V3 cannot distinguish "the scanner was wrong" from "the data was later
revised". Backtesting must replay stored `scan_runs`, not re-fetch history that has since
settled upward.

### 6. Cron go-live — staged, not switched

The cron currently runs `--fixture --profile production`. Drop `--fixture`.

**Do not go straight to persisting and broadcasting alerts.** Add an observation mode:
- Stage 1: run the real scan on the real schedule with `--dry-run` — full pipeline,
  `scan_runs` recorded, **no alerts persisted or broadcast**. Run it for several sessions.
- Stage 2: once alert volume and content look sane, remove `--dry-run`.

This exists because nobody knows yet how many candidates a morning produces. If the answer
is 200, the thresholds need tuning before the end user ever sees a dashboard full of noise —
and tuning is much easier from `scan_runs` data than from a user's disappointment.

Keep the generous UTC schedule and the ET gate as they are; that design is deliberate (see
the comments in `render.yaml`) and DST-safe.

### 7. Infrastructure changes in `render.yaml`

- Web service `plan: free` → `plan: starter` (always-on; free spins down after 15 min and
  breaks the dashboard's live updates).
- Move `alembic upgrade head` from `startCommand` to `preDeployCommand` — the hook requires
  a paid instance, which the line above provides. The exact change is already written in the
  `render.yaml` comments and `README.md` “Migration strategy”. A bad migration then stops the
  **deploy** instead of a **running service**.
- Add any new env vars (`RVOL_MODE=normalized`, settled-bar exclusion window, guard
  thresholds) with `sync: false` where they are secret, values inline where they are not.

## Constraints
- **Do NOT change stage arithmetic, thresholds, or the alert contract's meaning.** This
  phase changes where Stage 2's inputs come from, not what the stages decide.
- The fixture snapshot provider must keep working — CI stays offline, no live FMP in tests.
- Do NOT run against production Supabase.
- Any schema change: reversible migration, RLS on new tables, round-trip test on populated
  data.
- Demo-profile output must remain visibly badged and must never be mistakable for a real
  alert now that real alerts exist.
- **Out of scope, deliberately:** news/catalyst tagging moves to Phase 5 with the other
  enrichment signals. 4C is about the correctness of the core signal; adding a second new
  data source in the same phase makes a bad alert harder to diagnose.

## Definition of done
1. `run_scan.py --profile production --dry-run` against live FMP completes inside the
   5-minute cadence; report wall time, calls, and bytes for one pass
2. A live pass produces a plausible funnel; report survivor counts per stage and the
   candidates found
3. Normalized RVOL verified by test: live volume equal to profile → ~100%, at several clock
   times including near 09:25
4. The settled-bar symmetry is pinned by a test that fails if numerator and denominator use
   different cut-offs
5. A ticker with no profile falls back to simple RVOL and is flagged, not silently mixed
6. Empty-bar tickers are handled as "not trading", distinct from errors — with a test
7. Monotonicity and sanity guards fire on synthetic bad data and are recorded in `scan_runs`
8. Alert provenance fields are persisted and visible via the API
9. `render.yaml` updated: web on Starter, migrations in `preDeployCommand`, new env vars
10. Tests pass offline; ruff clean; migrations round-trip on populated data
11. Report: measured bandwidth for a full session (nightly + live), projected against the
    50 GB/30-day allowance, and a recommendation on whether the 5-minute cadence should be
    tiered early in the session
````

## Hotfix (live) — Session total mislabelled as scan result; confirmed vs faded candidates

**Status:** ✅ DONE (15 August 2026)
**Depends on:** live promotion (done)
**Size:** small — wording + list separation. No scanner logic.
**Why now:** this is the first thing the end user actually experiences, and he is now using
it daily.

> **Both numbers now travel separately.** `/status` returns `confirmed_count` alongside
> `alert_count`, and the panel labels them "Confirmed at 09:25" and "Seen this session".
> Neither stands in for the other, and the headline can no longer be contradicted by the
> funnel printed beneath it.
>
> **The third field is the one that makes it honest:** `final_pass_complete`. A confirmed
> count of 0 means two opposite things at 06:40 and at 09:26, so the panel reads "pending"
> rather than "0" until the authoritative pass has actually run. It is derived from the
> `is_final_pass` the pipeline already stamps into `stage_counts_json`, not from the clock
> at request time — the same rule as everywhere else in this codebase: the value shown is
> the value that was decided on. A run belonging to a later ET date than the alerts on
> screen counts as complete, so a finished session is never reported as still pending at
> 06:00 the next morning.
>
> **The cards are split, not filtered.** Confirmed first, faded behind a "show earlier
> candidates (26)" toggle sorted most-recently-seen first, on the alert's own
> `is_final_pass` — the API already published it, so nothing parses the entry-window
> string. Before 09:25 there is no split to make: one "Provisional candidates" list, since
> calling a 05:10 candidate faded at 06:40 would be false. Verified at 390px with a real
> mobile viewport: `scrollWidth == clientWidth == 390`, no element overflowing.

````
# Hotfix — Distinguish confirmed candidates from faded ones

## Bug 1 — The status panel states something untrue

Observed live, 14 August 2026:

    Last scan completed and surfaced 37 candidate(s).
    Last scan: 14/08/2026 13:25:17
    Candidates: 37

    Universe: 3964 | Stage 1: 741 | Stage 2: 28 | Stage 3: 11 | Risk filters: 11

The last scan surfaced **11**, not 37. The panel reports a **session total** under a
**per-scan** label, and the funnel immediately beneath it contradicts the headline.

Alert dedup is per ticker per session (`app/services/alerts/scanner_alerts.py`): one row
per `(ticker, session_date)`, updated in place across the morning's ~66 passes. So:

- **37** = distinct tickers that qualified at *any* point between 04:00 and 09:25 ET
- **11** = tickers still qualifying at the **09:25 authoritative pass**

Both numbers are worth showing. Only one of them is "what the last scan found".

**Fix:** state both, each labelled for what it is — e.g. *"11 candidates at the 09:25
confirmation pass · 37 seen across the session"*. Do not silently swap one for the other:
the session total is genuinely useful, it is simply not the last scan's result.

## Bug 2 — Confirmed and faded candidates compete for attention

The remaining 26 qualified earlier and then stopped: their gap closed, RVOL fell away, or
they ran into resistance. The alert card already records which pass last updated it, via
`suggested_entry_window()`:

- final pass → `09:30-10:00 ET (first 30 minutes of the regular session)`
- earlier pass → `monitor — provisional at 05:10 ET, confirmed at 09:25 ET`

That distinction is correct and deliberate — a candidate at 05:00 has four hours in which
to stop being one, so promising an entry window before confirmation would mislead. **But
it is carried only in small text on each card.** The user opens the dashboard at 09:26 to
37 cards, of which 26 are effectively expired, and must read each one to work out which 11
matter. That is precisely the wrong burden at the moment he is deciding what to trade.

**Fix:** separate them in the layout.
- **Confirmed candidates** (last updated by the authoritative pass) are the primary list,
  shown first and by default.
- **Faded candidates** are secondary — collapsed, or behind a "show earlier candidates"
  toggle, with a count.

Do **not** delete or hide the faded ones. A ticker that spiked at 05:10 and faded is real
information, and Phase 6 outcome labelling will want it. They simply must not compete with
the confirmed set.

This is the same principle already applied throughout this codebase — failed scan versus
quiet market, demo versus production, observation mode versus live. Make the distinction
that matters visible, rather than requiring the user to reconstruct it.

## Consider (propose rather than implement if it grows the phase)

- Before 09:25 there is no confirmed set at all — every candidate is provisional. The
  panel should read sensibly mid-session, not just after the final pass.
- A faded candidate that qualified at 09:20 is a different proposition from one that
  qualified at 04:30 and has been dead for five hours. Sorting the faded list by last-seen
  time, most recent first, costs nothing.

## Constraints
- **No change to scanner logic, stages, thresholds, scoring, or the alert contract's
  meaning.** This is presentation and wording only.
- No change to dedup or persistence — one row per (ticker, session) stays correct.
- If the API must expose which pass last updated an alert, extend the schema and
  regenerate TS types; do not have the frontend infer it from the entry-window string.
- Mobile-first: the confirmed/faded split must work on a 390px viewport without
  horizontal scroll.
- Existing demo badging, provisional-score labelling and "not financial advice" framing
  all stay.

## Definition of done
1. The status panel no longer describes a session total as the last scan's result; both
   numbers appear, each correctly labelled
2. Confirmed candidates are visually primary; faded ones are present but secondary
3. The panel reads sensibly **before** the 09:25 pass, when nothing is confirmed yet
4. Verified at 390px width
5. OpenAPI and generated TS types in sync if the API changed
6. Tests pass offline; ruff and eslint clean
````

---

## Hotfix (post-4C) — The 09:25 authoritative pass never runs

**Status:** ✅ DONE (11 August 2026)
**Depends on:** Phase 4C
**Size:** small — a comparison resolution, plus the `skipped` row it exposes

> **Fixed by truncating to whole minutes**, in one place: `clock.at_minute()`. The window
> gate, the final-pass check and `describe()` — the log header — all route through it, so
> the value printed *is* the value compared and the self-contradictory line cannot recur.
> A run at 09:25:10 ET is now inside the window and marked `is_final_pass`; 09:26:00 is
> still outside. Both bounds truncate, so 03:59:58 is not admitted as 04:00 either.
>
> **`SKIPPED` resolved by writing the row**, not by deleting the constant. Four places
> already documented that behaviour — the model docstring, the pipeline status table,
> `render.yaml` and `/status` — and only `_record()` disagreed. The row is the only
> durable answer to "did the cron fire?": Render's logs expire, and that was exactly the
> question this investigation had to answer. `_open_run()` therefore moved *above* the
> gate. No migration needed — the status is a string constant, not a DB enum.
>
> **Consequence handled:** ~18 heartbeat rows follow the 09:25 pass every session, so
> `/status` would have read "outside scan window", with no stage counts, from 09:30 ET
> until the next morning. Health is now computed from the last run that *attempted* work,
> queried directly rather than filtered out of the ten most recent rows. Skipped rows stay
> visible in `recent_runs`. `state='skipped'` survives for the one case that is genuinely
> it: the cron is alive but has never yet woken inside the window — distinct from
> `never_run`.

````
# Hotfix — Window boundary rejects the authoritative 09:25 pass

## The bug

Observed across two consecutive live sessions (10 and 11 August 2026): the cron run
scheduled at 13:25 UTC never produces a `scan_runs` row. Every other pass does. The last
recorded pass of the day is 13:20 UTC = 09:20 ET.

`docs/CLAUDE.md` §4.5 designates **09:25 ET as the authoritative pass** — the final
confirmation run that applies Stage 3 and issues the definitive alert set five minutes
before the open. It has never executed in production.

The log from that run contradicts itself:

    Scan time : 2026-08-11 09:25 EDT (UTC-04)
    SCAN SKIPPED — 2026-08-11 09:25 EDT is outside the 04:00-09:25 ET scan window

It reports 09:25 as outside a window whose stated upper bound is 09:25.

## Root cause

Render's scheduler has 10–45 s of startup latency (measured: runs scheduled at :00 begin
between :00:10 and :00:45). The pass scheduled at 13:25:00 UTC therefore starts around
13:25:10 UTC = **09:25:10 ET**.

The gate compares full timestamps, so `09:25:10 > 09:25:00` → outside → skip. The header
renders the same instant at minute resolution, so it prints "09:25". Both are internally
consistent; together they are nonsense to a reader, and the effect is that the single most
important pass of the day is silently discarded.

## The fix — compare at minute resolution

**Do not add a grace period or a fudge constant.** Truncate the comparison to whole minutes
so a run at 09:25:10 ET is treated as 09:25 and falls **inside** the window.

This is the same correction made in Phase 2 for percentage thresholds, and for the same
reason. There, `105 × 1.055 − 105` produced 5.499999999999996 and rejected a candidate whose
card displayed "5.50%" against a documented 5.5% bar; rounding first made the displayed
number and the decision agree. Apply the identical principle: **the value shown and the
value decided on must be the same value.**

Minute-resolution comparison is also what the spec means. §4.5 states a window of
04:00–09:25, not 04:00:00–09:25:00.000. It makes the behaviour independent of scheduler
latency rather than tolerant of a particular amount of it.

Apply the same truncation to **both** bounds, so a run starting at 07:59:58 ET is not
admitted as 08:00 when the window opens at 04:00 — the lower bound has the same class of
edge, currently masked because the 08:00 UTC run starts *after* 04:00 ET rather than before.

## Second defect, exposed by the same investigation

`ScanRunStatus.SKIPPED` exists in `app/models/scan_run.py` and its docstring is explicit:
*"Woke up outside the 04:00-09:25 ET window and did no work. Distinct from both 'completed
with zero candidates' and 'failed'."*

But a query across two full sessions returns **zero** rows with that status, against ~18
gate-rejected runs per day. The `running` row is documented as opening before work starts
(so a process killed mid-scan leaves a trace) — yet gate-skipped runs leave nothing.

Establish which is true and reconcile them:
- If skipped runs should record a row, open it before the gate check so `status='skipped'`
  is written. The database then distinguishes "cron fired and correctly skipped" from "cron
  never fired" — currently only Render's logs can tell those apart, and they expire.
- If the intended design is to write nothing, **remove `SKIPPED` from the model** and say so
  in the docstring. A status constant that can never appear is a false affordance: it
  invites a reader to write `where status = 'skipped'` and conclude, from an empty result,
  that the cron never woke up.

State which you chose and why. Do not leave the code and its own documentation disagreeing.

## Constraints
- Do NOT change stage arithmetic, thresholds, the alert contract, or the ET/DST conversion
  logic — only the resolution at which the boundary is compared.
- DST tests must still pass. Add a test at the exact boundary: a run at 09:25:10 ET is
  **inside**; one at 09:26:00 ET is **outside**.
- A migration is only needed if the skipped-row decision requires one; usual rules apply
  (reversible, RLS, round-trip on populated data).
- CI stays offline.

## Definition of done
1. A run starting at 09:25:10 ET executes the full scan and is marked the final pass
2. A run starting at 09:26:00 ET is still correctly outside the window
3. Boundary tests pin both, at both ends of the window
4. DST tests still pass
5. The `SKIPPED` inconsistency is resolved one way or the other, with the reasoning recorded
6. The self-contradictory log message can no longer occur — the time shown and the time
   decided on are the same value
7. Tests pass offline; ruff clean
8. Report: confirm on the next live session that a 13:25 UTC row appears and carries
   `is_final_pass = true`
````

---

## Hotfix (post-4C) — Separate `--no-alerts` from `--dry-run`

**Status:** ✅ DONE (8 August 2026)
**Depends on:** Phase 4C

> **The capability already existed**, as `--no-persist` — "run and record the scan, but do
> not persist or broadcast alerts". The cron used the wrong flag. Verified empirically
> before changing anything: `--dry-run` left `scan_runs` at 36 rows, `--no-persist` took it
> to 37.
>
> Renamed to `--no-alerts` anyway (with `--no-persist` kept as a deprecated alias), because
> "persist *what*?" is precisely the ambiguity that caused the bug. Modes are now explicit —
> `live` / `observation` / `dry_run` — recorded on the `scan_runs` row, stated in the CLI
> header, exposed on the API and in the OpenAPI contract, and badged on the Scans page.

````
# Hotfix — Add `--no-alerts` so the cron can be observed

## The bug
The production cron runs `run_scan.py --profile production --dry-run` and writes **nothing**.
Every five minutes it performs a full live scan, then discards the result:

    Dry run          : no scan_runs row will be written

The two-stage go-live in Phase 4C was specified as "full pipeline, `scan_runs` recorded, no
alerts persisted or broadcast". `--dry-run` does not do that — it was introduced in Phase 2
with the meaning "touch nothing in the database", and that is still its behaviour. The flag
was reused for a different purpose without checking its semantics.

Consequence: `scan_runs` has no rows since the Phase 4C deploy. There is nothing to observe,
and no basis on which to decide whether the thresholds are right. The `render.yaml` comment
block currently documents behaviour the code does not have.

## The fix

These are two genuinely different modes and need two flags.

1. **`--dry-run` — leave exactly as it is.** "Touch nothing." It is the correct semantics
   for local testing and is used elsewhere; do not redefine it.

2. **Add `--no-alerts`** to `scripts/run_scan.py`:
   - Runs the full pipeline against live data.
   - **Writes the `scan_runs` row normally** — status, per-stage counts, rejection reasons,
     timings, calls, bytes, integrity findings. This is the whole point.
   - Skips **only** alert persistence and the WebSocket broadcast.
   - The two flags may be combined; `--dry-run` wins (it is the stricter one).

3. **Make the mode unmistakable in the output.** The existing dry-run line was clear enough
   that the bug was caught from a single log line — preserve that quality. Each mode states
   plainly what will and will not be written, e.g.:
   - `Mode: observation (--no-alerts) - scan_runs WILL be written; alerts will NOT be`
   - `Mode: dry run - NOTHING will be written`
   - `Mode: live - scan_runs and alerts will be written and broadcast`

4. **Record the mode on the `scan_runs` row itself**, alongside the existing profile name.
   A run that produced no alerts because it was in observation mode must be distinguishable
   from one that produced none because the market was quiet. Same principle as the
   failure-vs-quiet-market distinction already in the design — apply it here.

5. **Update `render.yaml`:**
   - `startCommand` → `--profile production --no-alerts`
   - Rewrite the `--dry-run IS DELIBERATE` comment block: it describes the intended
     behaviour, not the actual behaviour. Say which flag now does what, and that promoting
     to live means deleting `--no-alerts`.

6. **Consider the dashboard**: if the Scans tab hides observation-mode runs, they are
   invisible for the purpose they exist to serve. Check, and surface the mode if it is not
   already shown. Propose rather than implement if it grows the phase.

## Constraints
- No change to stage arithmetic, thresholds, the alert contract, or scan behaviour — this
  changes only what is *written*.
- A migration for the mode column needs the usual: reversible, RLS, round-trip test on
  populated data.
- CI stays offline.

## Definition of done
1. `run_scan.py --profile production --no-alerts` writes a `scan_runs` row and no alerts
2. `run_scan.py --dry-run` still writes nothing
3. Both flags together behave as `--dry-run`, with a test
4. The mode is stated in the CLI output and stored on the `scan_runs` row
5. `render.yaml` uses `--no-alerts` and its comment block matches actual behaviour
6. Tests pass offline; ruff clean; migration round-trips on populated data
````

---

## Hotfix (post-4C) — Split-adjusted reference data + upside sanity suppression

**Status:** ✅ DONE (8 August 2026) — no longer blocks promoting the cron out of `--dry-run`.
**Depends on:** Phase 4C (pushed, deployed green)

> **⚠ Part 1's premise was disproved by measurement, and that is the main finding.**
> `historical-price-eod/full` is **already split-adjusted** — FFAI's June bars come back at
> 42.42 / 97,942 volume against a raw tape of 0.2828 / 14,691,299, both ratios exactly
> 150.0. Five of the seven flagged tickers never split. The reference data was correct; the
> tickers had genuinely collapsed (FFAI 32.06 → 4.38 in twenty sessions).
>
> So **Part 1 was a no-op** — there was no adjusted series to switch to, because we were
> already on it — and **Part 2 became the entire fix**, and a more necessary one: when the
> arithmetic and the data are both right, only a strategy filter can help.
>
> Delivered: `scan_upside_max` / `scan_price_regime_break_ratio` as risk filters with named,
> separately-counted rejection reasons. Live pass: 30 → 29 candidates, FFAI suppressed, top
> row now BCAR at 95.6% instead of FFAI at 540%. The 4C guard was renamed
> `split_distortion` → `price_regime_break`.

````
# Hotfix — Split-adjusted reference data + upside sanity suppression

## Context
Read `docs/FMP_PREMIUM_FINDINGS.md` and `docs/CLAUDE.md` §4.3 first.

Phase 4C's first live pass surfaced a data-quality problem the guards flagged but did not
prevent. `historical-price-eod/full` returns **unadjusted** prices, so any ticker that has
had a reverse split carries pre-split price levels in its reference data. FFAI's 20-day high
is 32.17 against a prior close of 4.67 — 6.9×, which no normal price action produces — making
its `sma_50` of 30.94 fiction and its computed upside **540%**.

14 findings across 7 tickers on a single pass: ADVB, CAPR, CLRO, FFAI, LABT, VEEE, WETO
(WETO at 20.6×). That is ~1% of the universe, but they land at the top of the list, not
randomly through it.

**This is structural for this strategy, not an edge case.** Sub-$5 low-float companies do
reverse splits routinely to maintain listing compliance, and Stage 1 selects for exactly that
universe. It will recur every month.

## Part 1 — Use split-adjusted history for reference data

Every Stage-3 input is affected: `high_yesterday`, `high_20d`, `sma_50`, `sma_200`, and
`price_close_yesterday`.

- Establish what FMP actually provides for adjusted vs unadjusted EOD series — inspect the
  endpoint's fields and any adjusted variant, and **measure it against the 7 known-bad
  tickers** rather than trusting the documentation. This project's record on unverified
  vendor claims is poor; the known-bad set is the cheapest regression test available.
- Switch reference-data computation to the adjusted series.
- If FMP does not expose a usable adjusted series, **say so plainly and propose
  alternatives** (detect ratio discontinuities in the daily series and adjust locally, or
  consume a split calendar). Do NOT silently ship a partial fix.
- Re-run the nightly refresh and verify: FFAI's `high_20d / price_close_yesterday` ratio
  should fall to a plausible range, and its upside should stop being 540%.

## Part 2 — Suppress implausible candidates, do not merely flag them

The sanity guard currently records a finding and prints it alongside the candidate table —
but the candidate still reaches the alert list. Change it to reject.

- A candidate whose upside exceeds a configurable ceiling, or whose reference data trips the
  ratio guard, is rejected as a **data-quality rejection**: a named rejection reason recorded
  in `scan_runs` alongside the existing reasons, not silently dropped.
- This is a **risk filter**, which `docs/CLAUDE.md` §4.3 explicitly provides for. It does
  **not** change Stage 1/2/3 arithmetic — do not touch the stage math.
- **Keep the guard even after Part 1.** Adjusted data fixes the known cause; the guard is
  what catches the next unknown one. Part 1 without Part 2 means trusting the feed.
- The threshold goes in config, with the measured basis documented.

## Part 3 — Make it visible

- Report data-quality rejections in the scan output and in `scan_runs`, **distinct from
  ordinary stage rejections**. "3 candidates suppressed for implausible reference data" is
  information; silently dropping them is not.
- Consider surfacing a count on the dashboard's scan-status panel — same principle as
  distinguishing a failed scan from a quiet market. **Propose rather than implement** if it
  grows the phase.

## Constraints
- Do NOT change stage arithmetic, thresholds, or the alert contract's meaning.
- Do NOT run against production Supabase.
- Reversible migration + round-trip test on populated data if the schema changes.
- CI stays offline; record fixtures for any new endpoint shape.

## Definition of done
1. Reference data for the 7 known-bad tickers is plausible after a refresh — report
   before/after ratios for each
2. FFAI no longer produces a 540% upside; state what it produces instead
3. If FMP has no adjusted series, that is reported with evidence and a proposed alternative
4. Implausible candidates are rejected with a named data-quality reason, visible in
   `scan_runs`
5. A test pins the guard using FFAI-shaped synthetic data
6. A live pass reports how many candidates the guard now suppresses
7. Tests pass offline; ruff clean
````

---

## Scheduled follow-ups (post-4C, neither blocking)

Both are small, both were disclosed in the 4C report, and both can run in either order
after the hotfix. Neither blocks promoting the cron out of `--dry-run`.

### Follow-up A — Tier the early-session cadence

**Status:** ready to run, and now measured rather than assumed
**Revised:** 15 August 2026, after profiling five live sessions

> **The original brief's premise was wrong, and the measurement is what caught it.** It
> argued the early session is uninformative because 48 tickers had no settled bars and
> the Tiingo probe saw 10× more trading tickers at 09:24 than 04:16. The scanner's own
> funnel does not behave that way: candidate yield is **flat from 04:15 to 08:40**, around
> 6–7 survivors a pass, and a 05:00 pass surfaces as many as an 08:00 one.
>
> Yield turned out to be the wrong measure. Scans are stateless and alerts dedup per
> ticker, so a run of passes each reporting 20 candidates can be one candidate set
> re-reported 20 times. **Churn is the deciding number**, and it says what yield hid — see
> the table in the brief. The conclusion survives; the reasoning behind it is now real.

````
# Follow-up — Tiered scan cadence for the early pre-market session

## Context
Phase 4C measured live bandwidth at **~47% of the 50 GB / 30-day allowance**, not the ~15%
Phase 4A projected. 4A assumed 554 tickers at ~9.6 KB mean payload; reality is 671 at ~15 KB
— both inputs were wrong in the same direction. Current figures: ~10.2 MB per pass, ~14.1 GB
per month live, ~23.6 GB total with the nightly cycle.

Still comfortable, but no longer a rounding error, and it grows with the universe: at the
current cadence the allowance is exhausted somewhere around 1,400 tickers.

## What the sessions actually show
Profiled from `scan_runs` across 10–14 August 2026 (5 sessions, 328 completed passes) with
`scripts/cadence_profile.py`. "First sightings" counts tickers a pass surfaced that no
earlier pass that morning had; "still confirmed" counts how many of those were still
candidates at the session's final pass.

| Window        | Passes/session | First sightings | Still confirmed | Keep rate |
|---------------|---------------:|----------------:|----------------:|----------:|
| 04:00–04:10   | 3              | 0               | 0               | —         |
| 04:15–04:20   | 2              | 32              | 8               | 25%       |
| **04:25–06:55** | **32**       | **50**          | **7**           | **14%**   |
| 07:00–07:55   | 12             | 34              | 8               | 24%       |
| 08:00–08:40   | 9              | 26              | 9               | 35%       |
| **08:45–09:25** | **10**       | **33**          | **24**          | **73%**   |

Three findings drive the design:

1. **04:00, 04:05 and 04:10 found nothing in 15 of 15 session-passes.** Not a quiet market
   — a structural impossibility. With the ~7-minute settling window the 04:00 bar is not
   trusted until 04:12, so those passes cannot produce a candidate by construction.
2. **Half the session's passes carry a seventh of its information.** The 32 passes between
   04:25 and 06:55 yield 1.4 confirmed-relevant first sightings per session between them.
3. **The last 40 minutes are the opposite.** 10 passes, 73% keep rate — this is the
   confirmation window and it must stay at 5 minutes.

Even finding 2 overstates the early passes. A ticker first seen at 05:40 and still
confirmed at 09:25 *stayed* a candidate throughout, so any later pass would have caught it.
Early sighting changes nothing about whether a candidate reaches the user.

## Why this is safe
**Scans are stateless.** The 09:25 pass recomputes every ticker from all bars since 04:00,
independent of what ran before it. No cadence change can alter the confirmed set. Cadence
governs only dashboard freshness before 09:25 and the completeness of the faded record.

## Scope
- **Open the window at 04:15, not 04:00.** Three passes per session that provably cannot
  find anything. This stands on its own and can ship first.
- Make the cadence **time-dependent and config-driven**, to this measured shape:

  | From  | Until | Interval |
  |-------|-------|----------|
  | 04:15 | 07:00 | 60 min (04:15 itself always runs — it is the discovery pass) |
  | 07:00 | 08:00 | 30 min |
  | 08:00 | 08:30 | 15 min |
  | 08:30 | 09:25 | 5 min  |

  19 passes rather than 66. Boundaries and intervals in config, not literals.
- The **09:25 authoritative pass must be unaffected** — guaranteed by statelessness, but
  test it explicitly anyway.
- Keep the generous UTC cron schedule and the ET gate exactly as they are; the gate is what
  makes this DST-safe and it is where the cadence rule belongs.
- Report measured bandwidth before and after, from the per-pass `bytes_used` now recorded
  on every run.

## The cost, stated plainly
Of 175 first sightings, 119 faded before the final pass. Those are the "spiked at 05:10 and
died" rows, and **Phase 6 outcome labelling is the customer for them** — a candidate that
faded is a negative training example, and coarsening the early session loses a share of them.

Be precise about what "loses" means here, because two different things get confused:

- **Outcomes are re-fetchable.** "Did it reach +5% by 10:30?" is a regular-hours question
  over liquid bars, measured across 30–60 minutes. Settled history answers it fine.
- **Decision-time inputs are not.** Three independent reasons, any one of which is enough:
  4A measured **49.4% of pre-market bars revised upward** within ~7 minutes of closing (the
  extreme case, AMIX's 04:10 bar, went from 16 to 1,161 — +7,156%), so a replay on settled
  bars would "detect" candidates nothing could have seen; `reference_data` is one current
  row per ticker, upserted nightly, so that morning's float, 20-day average volume and
  20-day high are gone; and `premarket_volume_profile` is likewise unique per
  `(ticker, bucket_minute)`, so the RVOL denominator is gone too.

**But the loss is smaller than the pass count suggests**, for a reason the churn table
itself supplies. At 0.2–0.6 new tickers per pass, consecutive early snapshots are
near-duplicates: 66 of them is not 66 observations, and treating them as independent
samples would produce confidence intervals far too tight to trust. Phase 6 needs a handful
of well-spaced anchors — 04:15, 07:00, 08:30 and 09:25 — **all of which the tiered cadence
keeps**. What actually disappears is transients that both appear and vanish inside a coarse
gap.

The change that would genuinely serve Phase 6 is orthogonal to this one: storing decision
time *values* rather than bare tickers. See Follow-up C, which is worth more than this
brief and does not depend on it.

## Constraints
- No change to stage logic, thresholds, or the alert contract.
- DST tests must still pass — a time-dependent cadence is one more thing that can drift.
- `scan_runs` heartbeat rows rise from ~18 to ~62 per session as more wake-ups skip. `/status`
  already computes health from the last run that attempted work, but check the Scans page,
  which shows the ten most recent runs and will otherwise show nothing but heartbeats.

## Definition of done
1. The window opens at 04:15; the three dead passes are gone, with a test
2. Cadence is config-driven and time-dependent; the 09:25 pass is provably unaffected
3. Measured bandwidth reported before and after, projected against 50 GB / 30 days
4. The Scans page still answers "is the scanner working?" under the heavier heartbeat rate
5. DST tests pass; tests pass offline; ruff clean
````

### Follow-up B — Make the profile build genuinely incremental

````
# Follow-up — Incremental pre-market volume profile rebuild

## Context
Phase 4B's stated intent was an incremental nightly profile update — add the newest session,
drop the oldest. The reported "5 calls, 9 seconds" was a **same-day re-run**, which is a
different thing: a fresh night still rebuilds all 20 sessions per ticker, at ~2,776 calls and
~140 MB. Disclosed in the 4C report.

Not harmful — roughly 4× more work than needed, on a nightly job with time to spare. Worth
fixing before the universe grows.

## Scope
- Genuinely incremental across days: fetch only sessions not already in
  `premarket_volume_profile`, recompute the rolling average, and drop sessions outside the
  window.
- `sessions_sampled` must stay accurate after an incremental update — it is what downstream
  code uses to decide whether a profile is trustworthy enough for normalized RVOL.
- Preserve idempotence and the `ON CONFLICT DO UPDATE` concurrency fix from 4B (two nightly
  runs overlapping on Render is a realistic scenario, and it already bit once).
- A `--rebuild` flag should still force a full reconstruction.
- Report actual calls and bytes for: a fresh incremental night, a same-day re-run, and a
  forced full rebuild — three distinct numbers, so the claim is unambiguous this time.

## Constraints
- No change to the profile's meaning or bucket definition — the settled-bar rule and the
  5-minute buckets stay exactly as they are.
- Round-trip migration test on populated data if the schema changes.

## Definition of done
1. A fresh night costs materially less than a full rebuild — all three figures reported
2. `sessions_sampled` is correct after incremental updates, pinned by a test
3. Concurrent runs still cannot corrupt a profile
4. Tests pass offline; ruff clean
````

### Follow-up C — Persist decision-time detail for Phase 6

**Status:** ✅ DONE (16 August 2026)
**Size:** small-to-medium — one table, one write path, no change to any decision
**Why it outranked Follow-up A:** A is a bandwidth optimisation. This one decides whether
Phase 6 can answer its questions at all, and every session that passes without it is a
session whose evidence is gone for good.

> **The sweep is now demonstrable, which is the only claim worth making.**
> `test_a_threshold_sweep_is_answerable_from_stored_rows` replays Stage 2's decision at a
> different RVOL floor from stored rows alone — no re-fetching, no reference-data join, no
> live scan — recovers the four real survivors exactly, and admits SLOW when the floor
> drops to 9%. If that test ever stops passing, the Phase 6 commitment is broken again.
>
> **Short-circuit evaluation is the one limit, and it is explicit rather than papered
> over.** A ticker rejected on gap never has RVOL computed, so widening the gap band
> surfaces tickers whose fate is *unknown*, not *passing*. `sweep_limitations()` states it
> in one place and the test pins the behaviour: FLAT comes back as unresolved.
> **Open decision:** evaluating every stage for every ticker regardless of earlier
> failures would remove the limit and costs no extra API calls — the data is already in
> memory — but it changes stage flow, which this brief put out of scope.
>
> **Cost measured, as the DoD asked.** 741 rows against Postgres: **225 ms median**
> (min 214, max 248), against a pass that does ~65 s of real work, on 1 pass in 66 plus
> three anchor passes writing ~16 rows each. Recording is best-effort and cannot fail a
> scan — `test_a_recording_failure_never_fails_the_scan` pins that a pass whose evidence
> write explodes still produces its alerts.
>
> **Retention: indefinite**, decided 15 August 2026. Revisit before that stops being true,
> not after a year of rows.
>
> One bug worth remembering, caught by the convergence test: clearing a run's existing
> rows with `session.delete()` does not work, because the ORM's unit of work flushes
> INSERTs before DELETEs — the deletes landed after the rows they were meant to make room
> for. It uses a Core `delete()` statement, which also avoids loading 741 objects to throw
> them away.

````
# Follow-up — Persist what the scanner saw, not just which tickers it liked

## The problem
`stage_counts_json` stores candidates as **plain ticker strings** and rejections as
`{ticker, stage, reason}` with no values. So for any pass, the scanner records *that* CRVO
was rejected at Stage 2, and never *what its gap and RVOL were*.

Phase 6 is specified as a replay over stored `scan_runs`. Three of its four stated goals
are blocked or degraded by this:

| Phase 6 goal | Blocked? | Why |
|---|---|---|
| Outcome labelling (+5% within the hour?) | No | Regular-hours bars, re-fetchable |
| Per-signal hit rates, fitted weights | No | The 09:25 alert row already carries features |
| **Threshold sensitivity sweep** | **Yes** | Needs rejected tickers' *values*; only reasons are stored |
| Early-vs-late detection value | Partly | Needs intra-session detail, currently tickers only |

The sweep is the one that matters most: `docs/PLAN.md` commits to justifying or revising
3% / 15% / 10% / 5.5%, and **that question cannot be asked of the data as stored today**,
at any scan cadence. Widening `gap_min` to 2.5% would surface tickers whose gap was never
written down.

## Why it cannot be fixed later
Re-fetching does not recover it. 4A measured 49.4% of pre-market bars revised upward within
~7 minutes of closing (worst case +7,156%), so settled history is not what the scanner
decided on. Worse, the denominators are simply gone: `reference_data` is one current row per
ticker upserted nightly, and `premarket_volume_profile` is unique per
`(ticker, bucket_minute)`. Neither keeps a single day of history.

**Every session that runs without this is unrecoverable evidence.** That is the whole
argument for doing it before Follow-up A rather than after.

## Scope
- A `scan_observations` table: one row per (scan_run, ticker) carrying the Stage-2 inputs
  and outcome — gap_pct, rvol_pct, rvol_mode, rvol_is_approximate, price, volume,
  bars_settled_through, provisional_bars_excluded, profile_sessions_sampled, the reference
  values used as denominators (volume_avg_20d, price_close_yesterday, high_20d, float), the
  stage reached, and the rejection reason if any.
- **Written for every Stage-1 survivor** (~741/pass) **at the 09:25 authoritative pass**,
  which is what makes the sweep possible over the true rejected population.
- **Written for candidates only** at three earlier anchors — 04:15, 07:00, 08:30 — so the
  early-versus-late question stays answerable at a granularity that survives the tiered
  cadence.
- Nothing else changes: same stages, same thresholds, same alerts, same contract. This is a
  write path, not a decision path.

## Sizing (why this is affordable)
| What | Rows/session | Rows/year (250) | ~Size/year |
|---|---:|---:|---:|
| Stage-1 survivors at 09:25 | ~741 | ~185,000 | **~19 MB** |
| Candidates at 3 anchors | ~60 | ~15,000 | ~2 MB |

Roughly 21 MB/year against Supabase's 500 MB. Versioning all of `reference_data` daily
would cost more and buy less — the per-observation copy of the denominators covers the
replay case without a second history table.

## Constraints
- **No change to stage logic, thresholds, scoring, or the alert contract.**
- Reversible migration, RLS on the new table, round-trip test on populated data.
- The write must not extend the pass materially or be able to fail it: ~741 rows is one
  bulk insert, and a failure to record observations must be logged, not raised.
- Retention: state a policy now (the sizing assumes indefinite; if that changes, say so
  before the first row is written, not after a year of them).

## Definition of done
1. `scan_observations` populated at the authoritative pass for every Stage-1 survivor,
   with the rejection reason and the values behind it
2. A threshold sweep is demonstrably answerable: a test or script that recomputes the
   candidate set at a different `gap_min` purely from stored rows
3. Anchor passes carry candidate detail; the anchors survive a tiered cadence
4. Pass duration measured before and after; the delta is reported
5. Migration round-trips on populated data; RLS present; tests pass offline; ruff clean
````

---

## ~~Phase 4A (Starter)~~ — SUPERSEDED, kept for reference only

**Starter was never purchased.** Its probe found no pre-market volume source, which is
what forced the jump to Premium. The live prompt is the **Premium** one above.

**Status:** superseded 5 Aug 2026
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

## Working notes

- One phase per session; verify Definition of done before advancing.
- The budget guard is the first thing built and the last thing bypassed — never exempt
  a "quick test" from it.
- CI never touches live FMP.
- Demo-profile output must always be visibly labelled — in logs, DB, and UI.
- **Alpaca code was removed in Phase 3.5** — done, 29 July 2026.
- **Starter was skipped entirely.** V1 (free) → V2 (Premium). Any text in this file
  referring to a Starter subscription is historical.
