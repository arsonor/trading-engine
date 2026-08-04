# Tiingo vs. FMP — Data Provider Evaluation

**Subject:** Can Tiingo's $30/month plan supply pre-market volume for the scanner?
**Compared against:** FMP Starter ($19/mo) and FMP Premium ($49/mo)
**Date:** July 2026
**Source:** Tiingo's official API documentation, read endpoint by endpoint

---

## 0. A note on how this evaluation was corrected

The first pass of this evaluation was wrong, twice, and both errors came from the same
cause: reading marketing pages and third-party wrappers instead of the primary API
documentation.

- **Error 1 — "Tiingo's intraday has no volume field."** False. Volume exists on both IEX
  endpoints. It is simply opt-in on the historical endpoint (`?columns=...,volume`), which
  is why a third-party R wrapper appeared to return no volume column.
- **Error 2 — "Tiingo's intraday is IEX-only, ~3% of the market."** True of the IEX
  endpoints, but Tiingo has a **separate consolidated endpoint** — Equity Realtime — that
  was missed entirely. It is the most relevant product they offer for this project.

Everything below is taken from the endpoint reference documentation directly.

---

## 1. The requirement

The scanner's Stage 2 needs two things during the pre-market session (04:00–09:30 ET):

1. **Pre-market price** → to compute the gap % versus the previous close.
2. **Cumulative pre-market volume** → to compute relative volume (RVOL), the conviction
   signal that separates a stock moving on real interest from one drifting on nothing.

Stage 1, which runs before either of those, needs a third thing:

3. **Share float** — the count of shares actually available to trade. The whole strategy
   rests on `float < 75,000,000`.

A provider must supply all three, or be combined with one that fills the gap.

---

## 2. What Tiingo actually offers

Tiingo has **three separate equity price products**, and the difference between them is
the crux of this evaluation.

### 2.1 IEX endpoints — `/iex/<ticker>`

Real-time data from the Investors Exchange only.

| Aspect | Detail |
|---|---|
| Coverage | 3,800–4,000 tickers quoted daily |
| Market share | **2.5–3%** of US volume (Tiingo states this themselves) |
| Volume field | Present, but **"the number of shares traded on IEX only"** |
| Top-of-book volume | IEX volume through the day; only becomes full-market volume *after* the official close |
| History | Intraday from August 2017 |

**Assessment:** volume exists but is a ~3% sample. Tiingo also notes that for less liquid
tickers it can take time to get an updated quote — which describes exactly the low-float
small caps this strategy targets. Not usable as a primary source for this project.

### 2.2 Equity Realtime endpoints — `/tiingo/equity/intraday` — **the relevant product**

This is the endpoint that changes the evaluation. Per Tiingo's documentation, it
*"creates datasets from multiple Equity venues (exchanges, ATS, and OTC venues)"*.

| Aspect | Detail |
|---|---|
| Source | **Consolidated** across exchanges, ATS and OTC venues |
| Session coverage | **04:00 ET to 20:00 ET** — the full pre-market window |
| Snapshot volume | *"Volume will be **consolidated intraday volume** throughout the day"* |
| All-tickers snapshot | **Yes — one request returns every ticker** (`/tiingo/equity/intraday`) |
| Historical intraday | OHLCV bars, configurable resampling, after-hours and force-fill controls |
| Historical volume | *"The **consolidated** number of shares traded for the interval"* |
| Status | **Beta** |

Three things here are genuinely excellent for this use case:

1. **Consolidated pre-market volume from 04:00 ET** — precisely the measurement the
   scanner needs, and the exact thing FMP Starter cannot provide.
2. **One request for the entire market.** The snapshot endpoint without a ticker returns
   all tickers. This is *better* than FMP Premium's batch-quote for a universe scanner:
   a full scan pass could cost a single request rather than hundreds.
3. **Historical intraday with after-hours support** — the raw material for building the
   20-session pre-market volume profiles that time-of-day-normalized RVOL requires.

**The caveat, in Tiingo's own words:** the endpoints are in beta, and *"for production use
cases, we recommend the IEX endpoints — which these endpoints expand upon."* The
documentation also warns that fields may be null when the underlying consolidated feed has
not published a value. A provider recommending against its own endpoint for production is
a material risk for a tool someone trades against.

### 2.3 BOATS — overnight (add-on, +$9/month)

Blue Ocean ATS overnight data: 12,000+ quotable securities, includes trades and volume.
But Blue Ocean is the **overnight** venue (roughly 20:00–04:00 ET). Its session *ends*
where the pre-market window begins. Potentially interesting as a supplementary signal —
overnight activity often precedes a morning gap — but it does not supply 04:00–09:30
cumulative volume.

---

## 3. The blocker: Tiingo has no float data

Stage 1 is the first gate in the pipeline and it filters on share float. Tiingo's
fundamentals product does not appear to supply it:

- Fundamentals are an **add-on subscription** at additional cost; only the DOW 30 are
  available on the standard plan for evaluation.
- The documented **daily metrics** are: `marketCap`, `enterpriseVal`, `peRatio`,
  `pbRatio`, `trailingPEG1Y`. **No float field.**
- Statement data may include **shares outstanding**, but that is not the same measurement.
  Outstanding shares include insider and restricted holdings; float is what is actually
  tradable. For a low-float strategy that distinction *is* the strategy.

There is also no equivalent of FMP's `company-screener` for building a universe by
liquidity criteria.

**Consequence: Tiingo cannot run this scanner on its own,** regardless of how good its
pre-market volume is.

---

## 4. Licensing — applies to whichever provider is chosen

Tiingo's terms are explicit: for Basic and Power accounts, data is for internal and
personal use only, and may not be redistributed in any form. The documentation names
*"a website or app"* as a redistribution use case. Display redistribution licensing starts
at $250/month for startups.

**However**, Tiingo's documentation carves out a developer exception: software built for
an audience that **requires users to submit their own Tiingo API token**, and which does
not itself distribute the data, does not require a redistribution licence.

That exception likely fits this project — the end user subscribes and supplies his own
key. It should be confirmed with Tiingo before relying on it.

The same question is open for FMP (Personal vs. Commercial pricing), so this is not a
point of difference between providers — but it does need resolving with whichever is
chosen.

---

## 5. Head-to-head comparison

| Requirement | **Tiingo Power** | **FMP Starter** | **FMP Premium** |
|---|---|---|---|
| Price (annual) | $30/mo ($300/yr) | $19/mo | $49/mo |
| Price (monthly) | $30/mo | $29/mo | $69/mo |
| **Pre-market consolidated volume** | **Yes** (beta) | **No** | **Yes** (`extended=true`) |
| Pre-market session covered | 04:00–20:00 ET | — | To verify |
| **Share float** | **No** | **Yes** (bulk, 1 call) | **Yes** (bulk, 1 call) |
| Universe screener | No | Yes | Yes |
| All-tickers snapshot | **Yes (1 request)** | No | Yes (batch-quote) |
| Historical intraday + after-hours | Yes (beta) | No | Yes |
| Rate limits | 10k/hr, 100k/day, no per-minute limit | 300/min | 750/min |
| Bandwidth | 40 GB/mo | 20 GB/mo | 50 GB/mo |
| EOD history | 30+ years | 5 years | 30 years |
| News | Included | Included | Included |
| Production readiness | **Beta** for the needed endpoint | Stable | Stable |
| Existing integration in our codebase | None | **Built** | **Built** |

### Where Tiingo genuinely wins

- **Rate limits.** No per-minute throttle at all — 100,000 requests/day. A burst scan of
  500 tickers runs instantly, where FMP would pace it across two minutes.
- **The all-tickers snapshot.** One request for the whole market's consolidated intraday
  volume is architecturally elegant and cheaper than any FMP equivalent.
- **EOD data quality.** Tiingo's composite-price error-checking is well regarded, and they
  give 30+ years on the base plan.
- **News depth.** 70M+ articles, 20+ years of history.

### Where Tiingo loses for this project

- **No float** — a hard blocker on Stage 1.
- **No screener** — universe construction has no cheap pre-filter.
- **Beta status** on the one endpoint that matters.

---

## 6. The arithmetic that decides it

Tiingo cannot stand alone, so the realistic options are:

| Path | Monthly cost | Pre-market volume | Float | Providers to integrate |
|---|---|---|---|---|
| Tiingo Power + FMP Starter | $30 + $19 = **$49** | Consolidated (beta) | Yes (FMP) | **Two** |
| **FMP Premium alone** | **$49** | Consolidated (stable) | Yes | **One (already built)** |
| Tiingo Power alone | $30 | Consolidated (beta) | **No — blocked** | One |
| FMP Starter alone | $19 | **No — blocked** | Yes | One (already built) |

**The two viable paths cost exactly the same.** At $49/month, the choice is between:

- **Two providers**, one of whose critical endpoint is in beta and which its own vendor
  advises against for production, requiring a second API client, second error taxonomy,
  second set of fixtures, and reconciliation between two data sources; or
- **One provider**, stable, with an API client, budget guard, fixture recorder and error
  handling already written and tested in this codebase.

---

## 7. Recommendation

**Subscribe to FMP Premium ($49/month annual, $69 month-to-month).**

The reasoning is not that Tiingo is a weaker service — for end-of-day data and news it is
arguably better — but that:

1. It cannot supply float, so it cannot replace FMP; it can only be added to it.
2. Adding it costs the same as simply upgrading FMP.
3. Its qualifying endpoint is beta, with the vendor explicitly recommending against
   production use.
4. The FMP integration already exists and is tested.

FMP Premium's `extended=true` parameter provides pre-market OHLCV bars, confirmed twice
by FMP support. That is the non-negotiable requirement, met, from a stable product.

### Worth doing anyway: a free Tiingo probe

Tiingo's Equity Realtime endpoint appears to be available at no cost — their
documentation notes they are *"the first company to make these exchange-compliant derived
metrics and offer them for free."* A free account therefore allows an empirical test:

- Pull `/tiingo/equity/intraday` for genuine low-float small caps during a live pre-market
  session.
- Check whether consolidated volume is present and accumulating from 04:00 ET.
- Compare coverage and data quality against FMP Premium's `extended=true` bars.

Cost: nothing but an hour. If Tiingo's consolidated feed proves solid and comes out of
beta, the single-request whole-market snapshot is compelling enough to revisit — it could
eventually be cheaper and faster than FMP for the live scanning half of the workload,
while FMP continues to supply float and the screener.

That is a future optimisation, not a launch decision.

---

## 8. Open questions

| # | Question | Why it matters |
|---|---|---|
| 1 | Does Tiingo's Equity Realtime cover genuine low-float small caps, or mainly liquid names? | Determines whether the consolidated feed is usable for this strategy at all |
| 2 | When does Equity Realtime leave beta? | Vendor currently advises against production use |
| 3 | Does Tiingo's fundamentals add-on include free float, or only shares outstanding? | Would remove the hard blocker if float is available |
| 4 | Does the developer-program exception cover an app where the end user supplies his own token? | Licensing clarity for either provider |
| 5 | How deep is Equity Realtime's historical intraday? | Needed for 20-session volume profiles and any backtesting |

---

## 9. Summary in one paragraph

Tiingo's $30 plan contains a genuinely strong product for this use case — a consolidated
intraday feed covering 04:00–20:00 ET with cumulative volume and a whole-market snapshot
in a single request — which is better on paper than anything FMP Starter offers. It is
undermined by two things: it is in beta with the vendor recommending against production
use, and Tiingo has no share-float data, which blocks the scanner's first filter outright.
Because Tiingo would therefore have to be *added to* FMP rather than replace it, and
because that combination costs exactly what FMP Premium costs alone, the simplest and
most robust path is FMP Premium. Tiingo remains worth a free probe, and worth revisiting
if its consolidated endpoint matures.
