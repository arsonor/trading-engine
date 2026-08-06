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

**Status:** ready — **run during a live pre-market session** (04:00–09:30 ET = 10:00–15:30 CEST)
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

## Phase 4B / 4C (V2) — written after 4A reports

**4B — Universe expansion + nightly refresh at scale.** Two-step build (`company-screener`
pre-filter → `shares-float-all` → exact `float < 75M` in SQL), sized by 4A's measured
counts, budget- and bandwidth-aware, idempotent and resumable.

**4C — Live snapshot provider, RVOL, cron go-live.** `FmpLiveSnapshotProvider` against
`extended=true` bars; `premarket_volume_profile` built from historical extended-hours data;
`RVOL_MODE` switched to `normalized`; decreasing-volume guard; market-tape check; cron wired
to the real scan; Render web service upgraded to Starter; migrations moved to
`preDeployCommand`.

Both are deliberately unwritten until 4A reports — writing them now would bake in the
assumptions this project has repeatedly had to correct.

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
