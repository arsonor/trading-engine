# FMP Premium — Measured Findings (Phase 4A)

**Session probed:** Thursday 6 August 2026, **live US pre-market**, from 04:05 ET.
**Tier:** Premium, purchased 5 August 2026 (month-to-month, $69).
**Instrument:** `backend/scripts/probe_fmp_premium.py` — throwaway; no product code changed.
**Raw evidence:** `backend/probe_output/fmp_premium/` (gitignored).
**Companion:** `docs/TIINGO_PROBE_FINDINGS.md` — same discipline, different provider.

---

## 0. Verdict first

**Premium delivers the thing it was bought for.** `extended=true` returns real pre-market
bars from **exactly 04:00 ET**, for genuinely low-float small caps as well as megacaps, with
per-bar volume that sums to true accumulated pre-market volume. The purchase is justified
and Phase 4B can proceed.

Three measured facts change the Phase 4B/4C design, and none of them were in the plan:

1. **`batch-quote` does not serve pre-market prices.** It works, and it accepts up to 1,000
   symbols — but during the pre-market window it returns the **previous** regular session's
   close. The live snapshot must be per-ticker `historical-chart/5min?extended=true`. The
   cheap batch path the plan assumed for live scanning does not exist. *(§5)*
2. **`volume` is per-bar, not cumulative.** `volume_premarket_accumulated` is a **sum over
   bars**, not a field read. *(§2, A.3)*
3. **Half of all bar volumes are revised upward after the fact.** 89 of 180 re-observed bars
   (**49.4%**) changed between identical requests; **all 89 rose, none fell**, median
   **+24.2%**, worst case +7,156%. Revisions settle within **7 minutes** of a bar closing, so
   excluding the most recent two bars gives stable data. Live RVOL otherwise *understates*
   true volume, and a replayed scan will not reproduce what the live scanner saw. *(§3)*

The saving grace for (1) is that the real Stage-1 universe is **554 tickers**, not
thousands — so per-ticker fan-out costs ~0.7 min per pass at 750 calls/min and ~15% of the
monthly bandwidth allowance. The design is viable; it is just not the design that was
sketched.

---

## 1. Method

Same three rules as the Tiingo probe, for the same reasons:

- **Raw payloads persisted before analysis.** In that probe a parsing bug produced a false
  negative recoverable only because the raw data was kept.
- **All calls go through the existing budget guard**, via `FmpClient._raw_get` +
  `interpret()`. That reuses the guard, retry policy and error taxonomy without adding
  endpoints to the production client. `FMP_DAILY_BUDGET` was raised from 230 (a free-tier
  value against a 250 hard stop) to **5,000**; Premium has no daily cap, so the guard's role
  becomes observability and runaway protection.
- **Semantics established by measurement, never by field naming.**

> **One conclusion in this document was wrong before it was checked, and it is worth
> recording.** An initial history probe requested `from=today-N` for N up to 1,200 days and
> got back **8 sessions every time**, byte-identical. Read naively that says extended-hours
> history is capped at 8 sessions and normalized RVOL is impossible. It is not: the cap is
> **per request**, truncating to the most recent portion of the requested range. Asking for
> an explicit *past* window returns that window in full, back to at least 2016 (§4). The
> difference between "impossible" and "paginate it" was one follow-up query.

---

## 2. (A) `extended=true` — the decisive test

**A.1 — Does it return pre-market bars? Yes.** At 04:05 ET, with the session barely open:

| Request | Bars | Pre-market bars |
|---|---:|---:|
| `historical-chart/5min?extended=true` | 1 | 1 |
| `historical-chart/5min` (no `extended`) | **0** | 0 |

The parameter is doing exactly what FMP claimed — with `extended=false` there is no
pre-market data at all, which is precisely why Starter was unusable.

**A.2 — Session start: exactly 04:00 ET.** Every ticker with pre-market activity returned a
first bar timestamped `04:00:00`. This holds on historical sessions back to 2016 as well.
**The timing model in `docs/CLAUDE.md` §4.5 needs no change.**

**A.3 — `volume` is PER-BAR, not cumulative.** Established by measurement:

```
AAPL  04:00  volume 30,243   close 313.21
      04:05  volume  9,965   close 314.00
      04:10  volume  2,822   close 313.96
```

Volume falls between consecutive bars, which a cumulative counter cannot do. Confirmed on
AMIX (9,669 → 3,541 → 16) and FFAI (5,584 → 201).

> **Consequence:** `volume_premarket_accumulated` = **sum of `volume` over bars from 04:00
> to now**. `docs/CLAUDE.md` §4.1 describes this field as "volume traded since 04:00 ET",
> which is correct, but any implementation that expects to *read* it rather than *sum* it
> will silently produce the last 5 minutes' volume instead of the session's.

**A.4 — Low-float small caps: yes, 17 of 20.** The test set is the actual Stage-1
population, not merely "small float" — it is the intersection of the screener pre-filter
(`price > $2`, `volume > 500K`, US, not ETF/fund) with `float < 75M`, so every name both
trades and passes Stage 1.

| Ticker | Float | Price | Avg volume | Bars | First bar | Σ pre-market vol |
|---|---:|---:|---:|---:|---|---:|
| SHAZ | 13,696 | $57.02 | 1,308,336 | 2 | 04:00 | 253 |
| FRGT | 91,291 | $3.42 | 515,336 | 2 | 04:00 | 1,594 |
| DBGI | 204,708 | $16.28 | 2,406,965 | 3 | 04:00 | 100 |
| EROC | 208,524 | $10.73 | 1,240,406 | 0 | — | **empty** |
| EZRA | 287,385 | $2.38 | 632,812 | 2 | 04:00 | 171 |
| DFNS | 396,252 | $45.91 | 3,395,513 | 3 | 04:00 | 4,067 |
| AMIX | 526,438 | $12.10 | 14,082,187 | 3 | 04:00 | 13,226 |
| SHPH | 582,385 | $4.60 | 1,563,710 | 3 | 04:00 | 1,347 |
| MEDS | 1,050,993 | $2.80 | 599,078 | 1 | 04:00 | 145 |
| IMSR | 1,177,079 | $5.35 | 1,337,254 | 0 | — | **empty** |
| ASTC | 1,383,379 | $9.11 | 3,941,510 | 3 | 04:00 | 816 |
| FFAI | 1,988,231 | $4.85 | 667,153 | 2 | 04:00 | 5,785 |
| OESX | 3,454,392 | $16.06 | 667,376 | 2 | 04:00 | 159 |
| SKYQ | 4,070,750 | $4.00 | 1,417,015 | 2 | 04:00 | 1,724 |
| OMDA | 4,568,914 | $19.11 | 1,963,385 | 1 | 04:05 | 1 |
| LIFE | 5,413,119 | $27.72 | 3,262,276 | 0 | — | **empty** |
| BLLN | 5,461,049 | $149.97 | 769,390 | 1 | 04:00 | 2 |
| MNTS | 5,711,719 | $4.24 | 1,837,574 | 1 | 04:00 | 7 |
| ARTV | 5,997,621 | $11.59 | 548,362 | 1 | 04:00 | 535 |
| QTTB | 6,403,251 | $16.49 | 623,699 | 2 | 04:00 | 833 |
| *AAPL (control)* | — | — | — | 3 | 04:00 | 43,030 |
| *TSLA (control)* | — | — | — | 3 | 04:00 | 45,847 |
| *MSFT (control)* | — | — | — | 3 | 04:00 | 34,548 |

Float coverage is genuine: the smallest is **13,696 shares**. No ticker returned a
restriction error, confirming FMP support's claim that `extended=true` is not filtered by
float or market cap.

**A.5 — Quiet tickers return an EMPTY ARRAY, not stale bars.** This is the good outcome and
it deserves emphasis, because the alternative is the dangerous one. EROC, IMSR and LIFE —
all liquid enough to pass the screener — returned `[]` rather than yesterday's bars. The
scanner can therefore distinguish *"has not traded pre-market"* from *"no data"* by row
count alone, with no staleness check needed on this endpoint.

The behaviour was confirmed by watching one of them start trading: **EROC returned `[]` at
04:15, 04:20 and 04:25, then 460 shares at 04:30.** An empty array means "nothing yet this
session" and converts to real bars the moment a trade prints — it is not a permanent
"unsupported symbol" signal, and must not be cached as one.

**A.6 — 1-minute bars also support `extended=true`**, from 04:00, and cost ~4× the payload
(5,401 B vs 1,296 B for the same session slice). 5-minute is the right default; 1-minute is
available if bar granularity ever matters.

---

## 3. (B.7) Data-integrity guard

The Tiingo probe found a cumulative counter that reset to zero mid-session and permanently
lost volume. FMP was not assumed immune. Two distinct failure modes were tested.

**No resets, no decreases.** Across the sampled series, **no ticker's summed pre-market
volume ever decreased**. The Tiingo failure mode does not occur here.

**But closed bars are revised upward.** Re-requesting an identical historical window returns
different volumes:

Measured across **16 samples over 75 minutes**, re-requesting the same window each time:

| | |
|---|---:|
| Bars observed more than once | 180 |
| Bars whose volume **changed** | **89 (49.4%)** |
| Revised **up** | **89** |
| Revised **down** | **0** |
| Median revision | **+24.2%** |
| 90th percentile | **+100%** |
| Largest revision | **+7,156%** (AMIX 04:10 bar: 16 → 1,161) |

Selected cases:

| Ticker | Bar | First read | Final read | Change |
|---|---|---:|---:|---:|
| AMIX | 04:10 | 16 | 1,161 | +7,156% |
| ASTC | 05:05 | 9 | 571 | +6,244% |
| ASTC | 04:45 | 10 | 210 | +2,000% |
| DFNS | 04:20 | 114 | 671 | +489% |
| FFAI | 04:25 | 298 | 1,096 | +268% |
| AAPL | 04:15 | 9,148 | 12,623 | +38.0% |

**Half of all bars are revised, and the revision can be an order of magnitude.** A bar first
reported as 16 shares finishing at 1,161 is not a rounding artefact — read live, it would
have put AMIX far below any RVOL threshold.

**But revisions settle quickly, and that is the usable part.** Measuring the gap between a
bar's close and the last time its volume changed:

| Time from bar close to final revision | Bars |
|---|---:|
| ≤ 5 min | 0 |
| **6–15 min** | **89 (100%)** |
| > 15 min | 0 |

Median **6 minutes**, maximum **7**. Every revision landed within roughly one and a half
5-minute intervals of the bar closing; none persisted beyond that, across 75 minutes of
observation. **A bar is provisional for ~7 minutes after it closes, and stable thereafter.**

> An earlier draft of this section reported "6 of 13 revisions were to bars two or more
> intervals old", implying revision was unbounded in time. That came from a metric that
> measured a bar's age at the *end of the run* rather than when it actually last changed —
> biased by construction, since most bars are old by then. The corrected measurement above
> is the one to design against.

This is ordinary late trade reporting on the consolidated tape rather than a defect, but it
has three consequences the scanner must own:

1. **Live RVOL systematically understates true volume.** The bias is *conservative* — the
   scanner may miss a candidate, it will never invent volume that did not occur. That is the
   safe direction, and the opposite of a false positive.
2. **A scan is not reproducible from the API.** Re-querying the 09:25 window later returns
   higher volumes than the live pass saw. **V3 backtesting must therefore replay stored
   `scan_runs` payloads, not re-fetch history** — otherwise the backtest calibrates against
   data the live scanner never had.
3. **The newest two bars are provisional; older ones are not.** Because revisions settle
   within 7 minutes, **excluding the most recent 2 bars (10 minutes) yields stable volume**
   — a bounded, cheap fix rather than an open-ended problem. The cost is 10 minutes of
   freshness at the 09:25 pass; the alternative is accepting a median 24% undercount on
   exactly the bars that signal a stock is moving *now*. Phase 4C should make this an
   explicit, configurable choice rather than an accident of implementation.

---

## 4. (C) History depth — normalized RVOL is viable

**C.8 — Extended-hours 5-minute history goes back to at least 2016.** Arbitrary past windows
return in full:

| Window requested | Sessions returned | Pre-market bars | First pre-market bar |
|---|---:|---:|---|
| 2026-06-01 → 06-05 | 5 | 330 | 04:00 |
| 2026-05-04 → 05-08 | 5 | 330 | 04:00 |
| 2026-01-05 → 01-09 | 5 | 330 | 04:00 |
| 2025-08-04 → 08-08 | 5 | 330 | 04:00 |
| 2024-08-05 → 08-09 | 5 | 326 | 04:00 |
| 2023-08-07 → 08-11 | 5 | 315 | 04:00 |
| 2021-08-09 → 08-13 | 5 | 254 | 04:00 |
| 2019-08-05 → 08-09 | 5 | 294 | 04:00 |
| 2016-08-08 → 08-12 | 5 | 180 | 04:00 |

**The limit is a per-request row cap, not a retention limit.** A broad range is silently
truncated to its most recent portion — which is what made the first probe read like an
8-session ceiling. Requesting one week at a time returns that week intact.

> **Verdict on normalized RVOL: YES.** The 20-session `premarket_volume_profile` is
> buildable at **~4 requests per ticker** (5 sessions each). This was scheduled as V3 work
> gated on data that turns out to be available now. Whether to build it in V2 is a
> sequencing decision, not a data one.

**C.9 — Low-float names have full pre-market history**, not sparse coverage: FFAI returned
309 and ASTC 330 pre-market bars across the same 5-session June window that gave AAPL 330.

---

## 5. (D) Scale endpoints

**D.10 — `batch-quote` works, caps at 1,000 symbols, and is USELESS for pre-market.**

| Symbols requested | Returned | Latency | Payload |
|---:|---:|---:|---:|
| 50 | 50 | 1.7 s | 18 KB |
| 500 | 500 | 0.30 s | 186 KB |
| 700 | 700 | 0.31 s | 258 KB |
| 1,000 | 1,000 | 0.34 s | 367 KB |
| 1,500 | **0** | 0.27 s | error |

No longer 402 — the free-tier restriction is gone. But queried at 04:22 ET it returned:

```
AAPL  price=311.00   volume=44,330,978   timestamp=2026-08-05 16:00:01 ET
TSLA  price=321.55   volume=27,820,813   timestamp=2026-08-05 19:59:59 ET
```

A 44-million-share volume and a timestamp from **yesterday's close** — while
`extended=true` showed AAPL trading at 313.96 with 43,030 pre-market shares. **`batch-quote`
serves the previous regular session during pre-market.** It is fine for nightly reference
data and useless as a live pre-market snapshot.

**D.11 — `shares-float-all`:** 5,000 rows per page, ~650 KB per page, 8 pages ≈ 5.2 MB for
**19,569 US symbols with float**, in about 7 seconds total. Fields: `symbol`, `date`,
`freeFloat`, `floatShares`, `outstandingShares`. Includes global symbols (`020Y.L`), so US
filtering is the caller's job. **11,504 US symbols have float < 75M.** The nightly float
refresh is ~8 calls, exactly as Phase 4B hoped.

**D.12 — `company-screener`** returns 15 fields — `symbol`, `companyName`, `marketCap`,
`sector`, `industry`, `beta`, `price`, `lastAnnualDividend`, `volume`, `exchange`,
`exchangeShortName`, `country`, `isEtf`, `isFund`, `isActivelyTrading` — and **no float**,
as expected. Universe sizing at `price > $2 AND volume > 500K`:

| Market-cap ceiling | Rows | Payload |
|---|---:|---:|
| < $2B | 1,340 | 492 KB |
| < $5B | 1,949 | 716 KB |
| none (global) | 3,540 | 1.30 MB |
| none, **US only** | 1,880 | 693 KB |

**The number that matters for Phase 4B:**

> **Stage-1 universe = screener (US, price > $2, vol > 500K) ∩ float < 75M = 554 tickers.**

That is an order of magnitude smaller than the "~2,000 survivors" Phase 4B was sized
against, and it is what makes per-ticker live scanning affordable despite D.10.

**D.13 — The §6.1 contradiction, re-checked.** The Tiingo probe found free-tier
`shares-float` returning real floats for 64 of 70 arbitrary small caps, contradicting FMP
support's "~87 symbols" statement. On Premium the question is moot operationally —
everything works — but the pattern stands: **vendor statements about tier limits have been
unreliable in both directions**, understating free-tier access and, here, overstating
`batch-quote`'s usefulness for pre-market. Measuring first was correct.

---

## 6. (E) Limits and bandwidth

**E.14 — 750 calls/min and no daily cap.** Not deliberately tested to exhaustion. Roughly
400 calls were made across this probe with no throttling, no 429, and no daily-cap error.
Sustained-rate behaviour at the 750/min ceiling remains unmeasured.

**E.15 — Bandwidth projection. Comfortable.** Measured payloads, full prior session:

| Ticker | Bars | Pre-market bars | Payload |
|---|---:|---:|---:|
| AAPL | 192 | 66 | 22.1 KB |
| FFAI | 182 | 57 | 19.4 KB |
| ASTC | 146 | 20 | 15.9 KB |

A full pre-market session is **66 five-minute bars** (04:00 → 09:25). Payload grows linearly
through the session, so the mean pass costs about half the full-session size (~9.6 KB).

| Workload | Volume |
|---|---:|
| Live scan: 554 tickers × 66 passes | 36,564 calls/session |
| Time per pass at 750/min | **0.7 min** — fits the 5-minute cadence with room |
| Bandwidth per session | **0.35 GB** |
| Per month (21 sessions) | **7.3 GB** |
| Nightly refresh (float + screener + EOD) | ~6 MB/session → 0.13 GB/month |
| **Total vs 50 GB / 30 days** | **~15% of allowance** |

Bandwidth is not a constraint at this universe size. It would become one if the Stage-1
universe grew past roughly 3,500 tickers, or if 1-minute bars were adopted (~4× payload).

---

## 7. What could not be determined

1. **Sustained behaviour at 750 calls/min.** Not provoked. A 36,564-call session at
   5-minute cadence is well inside the limit on average, but burst behaviour during a single
   pass is unmeasured.
2. **Whether the 7-minute settling window holds on heavier days.** Measured over 75 minutes
   of one ordinary session, where it held for all 89 revisions. A high-volume session with
   more late reporting could extend it; the "exclude the last 2 bars" rule should be
   validated again before it is relied on for the 09:25 pass.
3. **Whether revisions ever occur after the session ends.** Sampling stopped at ~05:31 ET,
   so a bar revised hours later — which would break the V3 replay assumption further —
   would not have been seen.
4. **Pre-market data on a low-liquidity day.** 6 August was an ordinary session; coverage on
   a holiday-shortened or very quiet day is untested.
5. **`batch-quote` behaviour during regular hours** — whether it becomes live intraday. Only
   the pre-market window was tested, which is the window that matters.
6. **Exact per-request row cap.** Observed truncation between 950 and 1,936 bars depending on
   interval and symbol; the precise rule was not isolated. Requesting ≤ 1 week at 5-minute
   granularity was reliable in every test.

---

## 8. Consequences for Phase 4B / 4C

**Confirmed — build as planned:**
- Nightly float refresh via `shares-float-all`: ~8 calls, 5.2 MB. As designed.
- Two-step universe build (screener → float → `reference_data`). As designed.
- Scan window 04:00–09:25 ET with the 09:25 authoritative pass. **No change needed** —
  bars genuinely start at 04:00.
- `gap_pct` from pre-market price. Works.
- The budget guard survives with a raised ceiling; bandwidth tracking should be added as
  planned, since bytes are the real limit even though the current projection is comfortable.

**Must change:**
1. **The live snapshot provider cannot use `batch-quote`.** It must call
   `historical-chart/5min?extended=true` per ticker and **sum** the bars. Phase 4C's
   `FmpLiveSnapshotProvider` should be designed around 554 per-pass calls, not one batch
   call. This is the single largest design change.
2. **`volume_premarket_accumulated` is a sum, not a read.** Any code treating it as a field
   will silently compute the last interval's volume.
3. **RVOL must be labelled as provisional on the most recent bars**, and the alert payload
   should record which bars were provisional at scan time — otherwise the +24.2% median
   revision is invisible downstream.
4. **V3 backtesting must replay stored `scan_runs`, never re-fetch history.** Re-fetched
   volume is systematically higher than what the live scanner saw, so a backtest against it
   calibrates the confidence score on data that never existed at decision time.
5. **`docs/CLAUDE.md` §6 still documents `FMP_DAILY_BUDGET=230`**, a free-tier value. It
   needs updating to the Premium ceiling alongside the Phase 4B work.

**Newly discovered constraint:**
- **Bar volumes are provisional for ~7 minutes after close, and half of them get revised.**
  Nothing in the plan anticipated revision, and it touches RVOL, the confidence score and
  backtesting at once. The mitigation is bounded — drop the newest two bars — but it must be
  a deliberate choice, and the 09:25 authoritative pass is exactly where the freshness cost
  of that choice is highest.

**Opportunity, not previously available:**
- **Normalized RVOL is unblocked.** 20+ sessions of extended-hours history at ~4 requests
  per ticker means `premarket_volume_profile` can be populated now. `docs/PLAN.md` and
  `docs/CLAUDE.md` both schedule this as V3 work gated on data availability; the gate is
  open. Sequencing it into V2 or leaving it in V3 is now a choice about effort, not data.
