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
