# Tiingo Free-Tier Probe — Measured Findings (Phase 4A-T)

**Session probed:** Tuesday 4 August 2026, live US pre-market. Two sampling windows:
**04:16–05:12 ET** (12 snapshots, 5-min cadence) and **08:38–09:29 ET** (7 snapshots,
spanning the 09:25 authoritative pass). 19 whole-market snapshots in total.
**Account:** Tiingo **free** tier (50 req/hour, 1,000/day, 1 GB/month).
**Instrument:** `backend/scripts/probe_tiingo.py` — throwaway, nothing wired into `app/`.
**Raw evidence:** `backend/probe_output/tiingo/` (gitignored; ~9 MB of gzipped snapshots).
**Companion:** `docs/TIINGO_VS_FMP_EVALUATION.md` (the documentation review this tests).

---

## 0. Verdict first

**Tiingo's consolidated Equity Realtime feed does what its documentation claims.** It
covers pre-market from 04:00 ET, its `volume` field is cumulative session volume rather
than per-trade size, and it carried **every one of the 37 float-verified low-float small
caps tested** — the case that actually decides this, and the one a megacap-only test would
have flattered.

But it is beta, and it behaved like beta: **one ticker in 37 reset its cumulative volume to
zero mid-session** while its trade timestamp advanced. Fed to RVOL unguarded, that produces
a confidently wrong low reading rather than a visible error.

Two findings from this probe matter **more than the Tiingo question itself**, and both
change what the free tier is believed capable of — see §6. They were incidental, and they
are the most valuable thing here.

---

## 1. Method, and why it is shaped this way

The 50 requests/hour ceiling is the binding constraint. Polling 13 tickers every 5 minutes
for an hour costs 156 requests and is simply impossible.

**The whole-market snapshot is the unit of sampling.** `/tiingo/equity/intraday/` with no
ticker returns every ticker Tiingo knows in one ~4 MB request. One call per interval covers
the entire market, so an hour of 5-minute sampling costs 12 requests, not 156.

**Raw payloads are persisted and analysed offline.** The pre-market window does not come
back until tomorrow, so the sampler commits to no ticker list — it stores complete
snapshots, and `--analyse` reconstructs any ticker's series afterwards. This is what let
the low-float test set be *chosen after* sampling had already started, and it is why the
nanosecond-timestamp bug below cost nothing.

Local ceiling set to 42/hour against Tiingo's 50, for the same reason `FMP_DAILY_BUDGET` is
230 against 250: a probe that exhausts its limit cannot be re-run to check a surprise.
Tiingo's own limit was never hit.

> **A parsing bug that nearly produced a false negative.** The first analysis reported
> 1 of 8,685 US tickers as fresh and would have condemned the feed as unusable. Tiingo
> returns **nanosecond** precision (`04:16:32.645031618-04:00`); Python 3.10's
> `datetime.fromisoformat` accepts only 3 or 6 fractional digits and raised on 6,386 rows,
> which the code counted as "stale". The historical endpoint adds a second quirk — a
> trailing `Z` — that 3.10 also rejects. Both are handled in `parse_ts()`. Every number
> below was recomputed after the fix; the stored summaries inside the earliest snapshot
> files still carry the pre-fix values and are never read back.

---

## 2. (A) Does the consolidated feed cover pre-market?

**A.1 — Fields populated during a live pre-market session.** Yes. Payload per ticker:

```json
{"ticker":"MVIS","timestamp":"2026-08-04T04:00:00.557500768-04:00","open":3.94,
 "high":3.94,"low":3.94,"tngoLast":3.94,"volume":6.0,"prevClose":3.82,
 "lqRefPrice":3.94,"lqSpread":null,"lqBidPrice":null,"lqAskPrice":null,"lqAskSize":null}
```

`ticker`, `timestamp`, OHLC, `tngoLast`, `volume` and `prevClose` are populated. The
liquidity fields (`lqSpread`, `lqBidPrice`, `lqBidSize`, `lqAskPrice`, `lqAskSize`) were
**null throughout pre-market** on every ticker inspected — so no bid/ask spread from this
endpoint during the window the scanner runs in.

`prevClose` being present alongside a live `tngoLast` means **`gap_pct` is computable from
this single endpoint**, with no second call and no reference-data join.

**A.2 — Does volume accumulate? Yes — it is cumulative session volume.**

Sampled every ~5 minutes. Controls and an active low-float name:

| Ticker | 04:16 | 04:21 | 04:26 | 04:31 | Reading |
|---|---:|---:|---:|---:|---|
| AAPL | 110,118 | 110,565 | 111,752 | 111,792 | rises |
| TSLA | 86,378 | 86,442 | 86,464 | 86,514 | rises |
| MSFT | 68,211 | 68,244 | 69,015 | 69,097 | rises |
| DXST (48,821 float) | 235,819 | 243,403 | 251,879 | 284,877 | rises |
| EZRA | 67 | 67 | 167 | 492 | rises |
| UPC | 0 | 644 | 918 | 1,438 | rises from zero |

Monotonic increase, never oscillation around a per-transaction size. A "trade size" field
would fluctuate up and down; none did, apart from the reset in §3.

> **A flat series is not a failure.** For a thin small cap that did not trade between two
> samples, an unchanged cumulative total is correct. The probe therefore reports *idle*
> and *not cumulative* as separate verdicts — conflating them would have condemned exactly
> the illiquid names this strategy targets. Only a **decreasing** series is evidence
> against cumulative semantics.

**A.3 — Does it start at 04:00 ET? Yes, and earlier.** The historical endpoint (§5) returns
pre-market bars whose earliest clock time within the 04:00–09:30 band is exactly **04:00**,
and bars exist before it (GSIT's most recent bar was 03:10 ET). The first live snapshot at
04:16 already showed 827 US tickers with a today timestamp, 16 minutes into the session.

Early and late samples were compared as the probe asked. At 04:16, 827 US tickers were
fresh and 376 trading; by 08:38 that had risen to 4,657 fresh and 3,677 trading. The feed
is live from the start of the window, and density grows steadily toward the open (§4).

---

## 3. (B) The critical question — low-float small caps

**B.4 — How the test set was built.** Not from memory. Candidates were taken from tickers
**observed trading in Tiingo's own live snapshot**, restricted to US common stock (via
Tiingo's supported-ticker list) priced at or above the strategy's $2 floor, then had their
floats **verified through the existing FMP client and its budget guard**.

70 checked → 64 returned a float → **37 have float < 75,000,000**, the Stage-1 cap. Floats
range from **32,174** to 67,114,518.

**B.5 — Per-ticker results.** Every one of the 37 was present in the feed in every sample.

*12 snapshots, 04:16:43–05:12:27 ET (the contiguous early window). Float from FMP `shares-float`; presence and volume from Tiingo's whole-market snapshot.*

| Ticker | Float | Prev close | In feed | Fresh | Pre-market volume first → last | Behaviour |
|---|---:|---:|:-:|:-:|---|---|
| AKAN | 32,174 | $5.41 | yes | 12/12 | 257 → 257 | idle (no trades) |
| DXST | 48,821 | $3.02 | yes | 12/12 | 235,819 → 507,794 | rises |
| QH | 68,571 | $4.79 | yes | 12/12 | 414 → 414 | idle (no trades) |
| TDIC | 71,488 | $2.52 | yes | 12/12 | 590 → 590 | idle (no trades) |
| ERNA | 99,796 | $3.48 | yes | 12/12 | 34 → 114 | rises |
| EDBL | 120,566 | $2.10 | yes | 12/12 | 0 → 947 | rises |
| SGLY | 277,472 | $5.12 | yes | 12/12 | 118 → 118 | idle (no trades) |
| EZRA | 287,385 | $2.26 | yes | 12/12 | 67 → 1,462 | rises |
| GNPX | 480,214 | $4.85 | yes | 12/12 | 962 → 1,270 | rises |
| UPC | 487,254 | $6.47 | yes | 12/12 | 0 → 7,223 | rises |
| BIYA | 602,366 | $3.02 | yes | 12/12 | 407 → 599 | rises |
| RUBI | 756,645 | $2.35 | yes | 12/12 | 251 → 2,244 | rises |
| PAVS | 856,186 | $4.85 | yes | 12/12 | 3,060 → 1 | **DECREASING** |
| LHSW | 1,027,371 | $2.69 | yes | 12/12 | 72 → 72 | idle (no trades) |
| ASTC | 1,378,381 | $6.77 | yes | 12/12 | 40 → 40 | idle (no trades) |
| XBIO | 1,818,984 | $2.92 | yes | 12/12 | 128 → 128 | idle (no trades) |
| HSCS | 1,956,269 | $2.20 | yes | 12/12 | 0 → 1 | rises |
| FFAI | 1,988,231 | $4.92 | yes | 12/12 | 496 → 699 | rises |
| PCSA | 2,338,215 | $2.12 | yes | 12/12 | 13 → 13 | idle (no trades) |
| GITS | 2,404,427 | $2.08 | yes | 12/12 | 26 → 26 | idle (no trades) |
| ACCL | 2,937,430 | $2.29 | yes | 12/12 | 1,028 → 1,028 | idle (no trades) |
| ASTI | 2,963,574 | $2.91 | yes | 12/12 | 50,672 → 50,672 | idle (no trades) |
| STKH | 4,047,685 | $2.77 | yes | 12/12 | 366 → 366 | idle (no trades) |
| SKYQ | 4,070,750 | $4.49 | yes | 12/12 | 4,035 → 4,098 | rises |
| BIRD | 4,433,230 | $2.34 | yes | 12/12 | 11 → 11 | idle (no trades) |
| SLBT | 6,412,944 | $3.28 | yes | 12/12 | 344 → 344 | idle (no trades) |
| RGC | 17,282,133 | $6.13 | yes | 12/12 | 86 → 86 | idle (no trades) |
| MVIS | 21,763,690 | $3.82 | yes | 12/12 | 6 → 6 | idle (no trades) |
| DPRO | 22,364,072 | $4.27 | yes | 12/12 | 0 → 10 | rises |
| ARCT | 26,153,203 | $5.99 | yes | 12/12 | 50 → 50 | idle (no trades) |
| OCCI | 29,097,650 | $2.46 | yes | 12/12 | 18,620 → 18,620 | idle (no trades) |
| GSIT | 32,594,112 | $6.13 | yes | 12/12 | 124 → 124 | idle (no trades) |
| GEMI | 33,076,918 | $3.96 | yes | 12/12 | 209,570 → 209,570 | idle (no trades) |
| SPCE | 62,222,762 | $2.81 | yes | 12/12 | 3,126 → 3,126 | idle (no trades) |
| SPRY | 64,498,883 | $5.46 | yes | 12/12 | 0 → 103 | rises |
| ABTC | 64,804,600 | $5.83 | yes | 12/12 | 7 → 7 | idle (no trades) |
| ASPI | 67,114,518 | $4.14 | yes | 12/12 | 500 → 500 | idle (no trades) |

**Tally:** 23 idle (no trades), 13 rises, 1 **DECREASING**. Present in every sample: **37/37**.


**At the authoritative pass, all 37 were live.** In the 08:38–09:29 window every one of the
37 low-float names carried non-null volume greater than zero in every sample — versus 13 of
37 showing movement in the quiet early window. Behaviour across the late window was **18
rising, 19 idle, and zero decreasing**. The reset described below did not recur.

This matters for how the early-window result should be read: the 23 "idle" verdicts in the
04:16–05:12 table are a quiet market, not absent coverage. By the hour that actually
governs the alert set, the entire low-float test set was trading and being reported.

**The PAVS reset, traced across the whole session.** The one failure is worth reading in
full, because its shape determines how an integration must defend against it:

| Trade timestamp (ET) | volume | tngoLast |
|---|---:|---:|
| 04:15:00 | 3,060 | 4.89 |
| 04:19:45 | 3,060 | 4.89 |
| 04:30:29 | 3,060 | 4.89 |
| **04:34:08** | **0** | 4.80 |
| 04:51:08 | 0 | 4.80 |
| 05:01:43 | 1 | 4.77 |
| 05:10:17 | 1 | 4.80 |
| 08:32:44 | 251 | 4.79 |

The counter did not blank transiently and recover — it **reset to zero and began
re-accumulating from a new baseline**, reaching only 251 by 08:32 against the 3,060 it had
already reported at 04:30. The trade timestamp advanced and the price moved throughout, so
every row looks healthy in isolation. The earlier volume is simply gone.

This is the worst possible failure shape for RVOL: not an error, not a null, but a
plausible small number. A ticker that had genuinely accumulated volume would be scored as
though it had barely traded, and would silently fail the `rvol_pct > 10` gate — removing a
real candidate rather than producing a visible fault.

**B.6 — Is the magnitude consolidated, or IEX-sized?** Directional evidence only, and it
supports the consolidated claim. At 04:31 ET, AAPL showed 111,792 shares. IEX runs ~2.5–3%
of consolidated volume, so an IEX-only feed would plausibly show low single-digit thousands
at that hour. DXST — a 48,821-float name — showed 306,946 shares, a figure a ~3% venue
sample would not produce for a stock that size. A same-instant FMP cross-check was **not
possible**: FMP's free tier serves no pre-market quote at all, which is the entire reason
this project is evaluating alternatives.

---

## 4. (C) The whole-market snapshot — the architectural prize

**C.7 — One request, the entire market.**

| Measure | Value |
|---|---|
| Tickers returned | **15,937–15,938** |
| Payload size | **~4.17–4.19 MB** uncompressed (≈780 KB gzipped on disk) |
| Latency, 04:16–05:12 | **2.4–3.1 s** (12 calls) |
| Latency, 08:58–09:29 | **3.5–17.7 s** (7 calls) — see below |
| US common stock among them | **8,685** |
| `volume` non-null | **100%** |

> **Latency is highly variable and NOT explained by time of day.** An earlier draft of this
> document claimed the slowdown was contention as the open approached. Later sampling
> disproved that: 19 further snapshots taken during regular hours (11:51–12:38 ET) ranged
> from **2.3 s to 12.5 s**, with a 2.3 s call and a 9.6 s call five minutes apart on an
> identical payload. There is no time-of-day pattern.
>
> Two things are worth separating. The pre-market spikes (14.0 s at 09:08, 13.2 s at 09:18,
> **17.7 s at 09:29**) came from a single sampling process and are genuine. The
> regular-hours figures are **confounded** — two probe processes were unintentionally
> sampling concurrently on the same token, and in every close pair the *second* call is the
> slow one (11:56:40 → 2.6 s, 11:57:21 → 7.2 s; 12:01:44 → 2.3 s, 12:02:30 → 8.3 s). Some
> of that slowness is self-inflicted and should not be attributed to Tiingo.
>
> What survives is the operational point, unchanged: the snapshot call is **2.3–17.7 s**,
> unpredictably, on a constant ~4.2 MB payload. A live integration needs a timeout budget
> set from the worst case, not the median — and must not issue overlapping requests.

**C.8 — Freshness rises through the session,** which is the correct shape: a ticker carries
yesterday's close until it trades today.

| ET | Fresh (today) | Trading (vol > 0) | % of 8,685 US fresh |
|---|---:|---:|---:|
| 04:16 | 827 | 376 | 9.5% |
| 04:31 | 1,061 | 505 | 12.2% |
| 04:47 | 1,111 | 553 | 12.8% |
| 05:02 | 1,163 | 579 | 13.4% |
| 05:12 | 1,198 | 598 | 13.8% |
| 08:38 | 4,657 | 3,677 | 53.6% |
| 08:58 | 4,678 | 3,693 | 53.9% |
| 09:08 | 4,691 | 3,701 | 54.0% |
| 09:18 | 4,699 | 3,701 | 54.1% |
| **09:24 (authoritative pass)** | **5,024** | **3,984** | **57.8%** |
| 09:29 | 5,050 | 3,971 | 58.1% |

The early window climbs slowly — 827 → 1,198 fresh over 56 minutes. The final hour is a
different market: **5,024 fresh and 3,984 actively trading at the 09:24 pass**, a 10×
increase in tickers carrying live volume versus 04:16. Coverage is therefore strongly
time-dependent *within* the session, and the scanner's authoritative 09:25 pass sees by far
the densest market of the window. Thin early coverage is the market being quiet, not the
feed being incomplete — which also means a 04:00 scan is scanning a genuinely small
tradeable set, whatever the provider.

For scale, 19 further snapshots taken during **regular hours** (11:51–12:38 ET) showed
**11,001–11,073** fresh US tickers — roughly double the 09:24 pre-market figure and 13× the
04:16 one. These fall outside the scanner's window and answer none of questions A or B, but
they confirm the ceiling: the feed's coverage is not the constraint, the pre-market session's
own thinness is.

At 04:47 the timestamp distribution was: **9,510** tickers stamped 2026-08-03 (yesterday's
close, untraded so far), **1,783** stamped today, the remainder older — stale or delisted
names the feed still carries. **Staleness is therefore explicit and detectable per row**;
a consumer must filter on `timestamp`, because a stale row is well-formed and looks usable.

**C.9 — All 37 low-float names appeared in the whole-market snapshot**, in every sample.

**Bandwidth is the real constraint, not the request count.** At ~4.17 MB per snapshot, a
5-minute cadence across the full 04:00–09:25 window is 66 calls ≈ **275 MB per session** —
which exhausts the free tier's 1 GB/month in four sessions. Request count is never the
issue (66 « 1,000/day); payload volume is.

---

## 5. (D) Historical intraday — can volume profiles be built?

**D.10 — Volume is returned when explicitly requested.** `?columns=open,high,low,close,volume`
with `afterHours=true`. All 7,997 MVIS bars and all 10,000 GSIT bars carried volume. Omit
`columns` and volume is absent — the opt-in behaviour the evaluation document predicted.

**D.11 — Depth: a hard 10,000-row cap per request, not the IEX 2,000.**

| Ticker | Requested | Bars | Sessions | Pre-market bars | Sessions w/ pre-market | Earliest |
|---|---:|---:|---:|---:|---:|---|
| MVIS | 40 days | 7,997 | 35 | 1,782 | **27** | 2026-06-25 |
| GSIT | 400 days | **10,000** (capped) | 43 | 2,244 | **34** | 2026-06-16 |

Requesting 400 days returned exactly 10,000 rows covering 43 sessions — the cap truncates
the *start*, returning the most recent bars. At 5-minute resolution this is ~43 sessions
per request, and older data is reachable by paginating with `endDate`.

**The 20-session pre-market volume profile is obtainable in a single request per ticker.**
34 sessions with pre-market bars comfortably exceeds the 20 required.

**D.12 — Pre-market bars are included, from 04:00 ET** (and before — GSIT's latest bar was
03:10 ET).

---

## 6. Two findings that outrank the Tiingo question

Both were incidental to this probe and both contradict assumptions currently written into
the project's own planning documents.

### 6.1 FMP `shares-float` is NOT restricted to the free tier's ~43-symbol sample

This is the significant one. `docs/PLAN.md` records that the free tier serves only ~43
accessible symbols, and `reference_data` contains only megacaps — the smallest float in the
database is ADBE at 396,228,000, five times above the 75M Stage-1 cap.

**That limitation is on `quote` and `historical-price-eod`, not on `shares-float`.** Float
was retrieved for arbitrary small caps on the **free** tier during this probe — 64 of 70
requested tickers returned a real float, including AKAN at 32,174 and DXST at 48,821.

`reference_data` holds only megacaps because the universe was built from `quote`
accessibility, not because float was unavailable. **A genuine low-float universe appears
buildable on the free tier today**, which bears directly on Phase 4A and on what the FMP
Starter upgrade is actually being bought for. This deserves a probe of its own before that
subscription decision is made.

### 6.2 Free-tier Tiingo supplies the pre-market bars PLAN.md attributes to FMP Premium

`docs/CLAUDE.md` §4.1 and `PLAN.md` both place the 20-session `premarket_volume_profile` in
V3, gated on FMP Premium's `extended=true`. Tiingo's free tier returned **5-minute
pre-market bars with volume, from 04:00 ET, across 34 sessions, in one request**.

The normalized-RVOL work is therefore not necessarily Premium-gated. It may be a data-source
choice rather than a tier upgrade.

---

## 7. (E) Coverage and limits

- **E.13 — Supported tickers.** `supported_tickers.zip` (static CDN file, no auth, outside
  the API quota): **107,750 rows**, of which **16,370** are US-exchange common stock —
  NASDAQ 9,242, NYSE 6,285, AMEX 339, BATS 267, NYSE MKT 193, NYSE ARCA 44. The live
  snapshot carries 15,937 tickers, 8,685 of them US common stock.
- **E.14 — Rate limits.** 50/hour confirmed as documented; **never hit**, by design. Peak
  local usage was 17 of the 42 ceiling in one hour. No 429 was observed, so throttling
  *behaviour* remains unmeasured.
- **E.15 — Entitlements.** Everything used here worked on the free account: whole-market
  snapshot, per-ticker snapshot, historical intraday with volume and after-hours. No
  endpoint returned a payment-required error.
- **Unknown tickers fail silently.** `/tiingo/equity/intraday/ZZZZNOTREAL` returns
  **HTTP 200 with `[]`**, not a 404. Any integration must treat an empty array as "unknown
  or no data", since it is indistinguishable from a quiet ticker by status code alone.
- **Redirect.** The collection endpoint 301s to a trailing slash; without `follow_redirects`
  the client silently receives an empty body.

---

## 8. What could not be determined

1. **Same-instant magnitude cross-check against FMP** (B.6). Impossible on FMP's free tier,
   which serves no pre-market quote. Only a plausibility argument is offered.
2. **Whether the PAVS volume reset is rare, periodic, or ticker-specific.** Observed once in
   37 names, and traced across a full session (§3) — the reset is real and permanent, not
   transient. But one occurrence in one session cannot establish a *rate*, which is what an
   integration decision needs. Multi-session sampling is required.
3. **Throttling behaviour at the 50/hour limit.** Deliberately not provoked.
4. **Bid/ask spread during pre-market.** All `lq*` fields were null; whether they populate
   during regular hours was not tested.
5. **Whether float itself is available from Tiingo.** Not tested — the evaluation document
   already establishes Tiingo has no float product, and FMP covers it (§6.1).
6. **Sub-04:00 coverage.** Bars exist at 03:10 ET but the 04:00-and-earlier boundary was not
   systematically characterised.

---

## 9. Verdict — the three questions asked

**1. Can Tiingo measure cumulative pre-market volume for low-float small caps?**
**Yes, with a caveat that must be engineered around.** All 37 float-verified low-float names
were present in every sample, `volume` is cumulative session volume, and it accumulates from
04:00 ET. The caveat is the observed mid-session reset to zero (1 of 37, ~2.7%): a consumer
must retain the previous sample per ticker and treat a decrease as a data fault, because an
RVOL computed from a reset value is wrong in the confident direction.

**2. Is the whole-market snapshot viable as a live-scan source?**
**Yes on coverage, with two caveats — bandwidth and latency-at-the-open.** One request,
~15,900 tickers, 100% non-null volume, 5,024 of them fresh at the 09:24 pass. It is
architecturally better than anything FMP offers: it removes per-ticker fan-out entirely and
makes scan cost independent of universe size, which is the single biggest structural problem
in the current V2 design.

The caveats are both real. **Bandwidth:** ~4.19 MB per call means a full 5-minute-cadence
session is ~275 MB, exhausting the free 1 GB/month in four sessions — this needs a paid
Tiingo tier for its allowance, not for its endpoints. **Latency:** the call takes anywhere
from **2.3 s to 17.7 s** on a constant payload, unpredictably and with no time-of-day
pattern. Neither is disqualifying, but both must be designed for rather than discovered in
production.

> This probe alone consumed **163 MB** across 39 whole-market snapshots — 16% of the free
> monthly allowance in a single day, and a concrete demonstration that bandwidth, not
> request count, is the free tier's binding limit.

**3. Does this justify revisiting the FMP-Premium recommendation?**
**Not on this evidence alone — but §6.1 might, and that is the finding to act on.**
Tiingo remains beta, has no float data, and showed a real integrity defect on precisely the
low-float names the strategy targets. The recommendation of FMP Premium stands. However,
this probe incidentally established that **FMP's free tier already returns float for
arbitrary small caps**, and that free-tier Tiingo already returns the pre-market bars the
plan attributes to Premium. Both bear directly on what the FMP Starter/Premium upgrade is
being purchased for, and both are cheap to settle before committing.

**Recommended next step:** run Phase 4A as planned, but add a specific question — *what
does FMP Starter provide that the free tier plus §6.1 does not already?* That is now a
measurable question rather than a rhetorical one.
