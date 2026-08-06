"""Phase 4A — measure what FMP Premium actually delivers.

    uv run python scripts/probe_fmp_premium.py --extended            # A.1-A.3, A.6
    uv run python scripts/probe_fmp_premium.py --lowfloat            # D.11 -> test set
    uv run python scripts/probe_fmp_premium.py --probe-set           # A.4, A.5
    uv run python scripts/probe_fmp_premium.py --sample-series --minutes 60 --interval 5
    uv run python scripts/probe_fmp_premium.py --history             # C.8, C.9
    uv run python scripts/probe_fmp_premium.py --scale               # D.10, D.12
    uv run python scripts/probe_fmp_premium.py --analyse             # offline, 0 calls

WRITES NO PRODUCT CODE. Premium was bought for one claim — `extended=true` yields real
pre-market volume — and that claim has never been measured. This measures it before
Phase 4B builds on it.

Three design choices, each learned from the Tiingo probe (`docs/TIINGO_PROBE_FINDINGS.md`):

1. **Raw payloads are persisted before anything is analysed.** In that probe a
   timestamp-parsing bug produced a false negative that was only recoverable because the
   raw data had been kept. Same rule here.

2. **Calls go through the existing budget guard**, via `FmpClient._raw_get` +
   `interpret()`. That reuses the guard, the retry policy and the full error taxonomy
   without adding endpoints to the production client — the phase is required to leave
   product code untouched, and a throwaway probe should not widen the client's surface.

3. **Cumulative-vs-per-bar is established by measurement, not by field naming.** The Tiingo
   probe found a cumulative counter that silently reset to zero; FMP is not assumed immune.

Nothing here is imported by `app/`. Deleting this file, `docs/FMP_PREMIUM_FINDINGS.md` and
`probe_output/fmp_premium/` removes the phase.
"""

import argparse
import asyncio
import json
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _bootstrap  # noqa: F401,E402  (puts backend/ on sys.path for app.* imports)

from app.services.fmp.client import FmpClient  # noqa: E402
from app.services.fmp.parsing import interpret  # noqa: E402

ET = ZoneInfo("America/New_York")
OUT = Path(__file__).resolve().parent.parent / "probe_output" / "fmp_premium"

log = logging.getLogger("fmp_premium_probe")

# Megacap controls. Present so that a failure on low-float names can be distinguished from
# a failure of the endpoint itself — the distinction the whole of section A turns on.
CONTROLS = ["AAPL", "TSLA", "MSFT"]


# ----------------------------------------------------------------------------- plumbing


def in_premarket(now: datetime | None = None) -> tuple[bool, datetime]:
    now = now or datetime.now(ET)
    live = now.weekday() < 5 and (4, 0) <= (now.hour, now.minute) < (9, 30)
    return live, now


async def call(client: FmpClient, endpoint: str, params: dict[str, Any],
               symbol: str | None = None) -> tuple[Any, dict]:
    """One measured call through the budget guard. Returns (payload, meta)."""
    started = time.time()
    raw = await client._raw_get(endpoint, params)
    elapsed = time.time() - started
    body = raw.payload
    meta = {
        "endpoint": endpoint,
        "params": {k: v for k, v in params.items() if k != "apikey"},
        "status": raw.status,
        "elapsed_s": round(elapsed, 2),
        "bytes": len(json.dumps(body)) if body is not None else 0,
        "rows": len(body) if isinstance(body, list) else None,
        "requested_at_et": datetime.now(ET).isoformat(),
    }
    try:
        interpret(raw, endpoint=endpoint, symbol=symbol)
    except Exception as exc:  # a restriction or error is a datum, not a crash
        meta["error"] = f"{type(exc).__name__}: {exc}"
    return body, meta


def write(name: str, payload: Any, meta: Any) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps({"meta": meta, "payload": payload}, indent=2), encoding="utf-8")
    log.info("  wrote %s (%s bytes)", path.name, f"{path.stat().st_size:,}")
    return path


def load(name: str) -> dict | None:
    path = OUT / f"{name}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def bar_time(bar: dict) -> datetime | None:
    """FMP intraday bars carry naive 'YYYY-MM-DD HH:MM:SS' in ET."""
    raw = bar.get("date")
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET)
    except (ValueError, TypeError):
        return None


def premarket_bars(bars: list[dict]) -> list[dict]:
    out = []
    for b in bars:
        t = bar_time(b)
        if t and (4, 0) <= (t.hour, t.minute) < (9, 30):
            out.append(b)
    return out


# ------------------------------------------------------------------ A. extended=true


async def mode_extended(session: str) -> int:
    """A.1-A.3, A.6 — does extended=true return pre-market bars, from when, and is
    `volume` per-bar or cumulative?"""
    live, now = in_premarket()
    results: dict[str, Any] = {"session": session, "live_premarket": live,
                               "captured_at_et": now.isoformat()}

    async with FmpClient() as c:
        for interval in ("5min", "1min"):
            for ext in ("true", "false"):
                key = f"{interval}_extended_{ext}"
                bars, meta = await call(
                    c, f"historical-chart/{interval}",
                    {"symbol": "AAPL", "from": session, "to": session, "extended": ext},
                    symbol="AAPL")
                results[key] = {"meta": meta, "bars": bars}
                n = len(bars) if isinstance(bars, list) else 0
                pm = premarket_bars(bars) if isinstance(bars, list) else []
                earliest = min((bar_time(b) for b in pm), default=None)
                print(f"  AAPL {interval:5} extended={ext:5}  bars={n:>4}  premarket={len(pm):>4}"
                      f"  earliest_pm={earliest.strftime('%H:%M') if earliest else '-'}"
                      f"  {meta['elapsed_s']}s  {meta['bytes']:,}B")

    write(f"extended_{session}_{now:%H%M%S}", results, {"mode": "extended"})

    # A.3 — per-bar or cumulative? Decided by measurement.
    five = results.get("5min_extended_true", {}).get("bars")
    if isinstance(five, list) and len(five) >= 3:
        pm = sorted(premarket_bars(five), key=lambda b: bar_time(b))
        vols = [b.get("volume") for b in pm if b.get("volume") is not None]
        if len(vols) >= 3:
            rising = all(b >= a for a, b in zip(vols, vols[1:]))
            print(f"\n  A.3 volume semantics — {len(vols)} pre-market bars")
            print(f"      first 6: {vols[:6]}")
            print(f"      monotonically non-decreasing: {rising}")
            print("      VERDICT:", "cumulative (suspicious — verify)" if rising
                  else "PER-BAR (values rise and fall independently) -> sum for accumulated")
        else:
            print("\n  A.3 needs >=3 pre-market bars; only", len(vols), "so far. Re-run later.")
    else:
        print("\n  A.3 deferred — too few bars this early in the session.")
    if not live:
        print("\n  NOTE: run OUTSIDE the live pre-market window; A answers are not valid.")
    return 0


# ------------------------------------------------------------------ D.11 / A.4 test set


async def mode_lowfloat(target: int, max_pages: int) -> int:
    """D.11 + build the A.4 test set: real low-float US names, float < 75M, price > $2."""
    floats: dict[str, dict] = {}
    page_meta = []
    async with FmpClient() as c:
        for page in range(max_pages):
            rows, meta = await call(c, "shares-float-all", {"limit": 5000, "page": page})
            page_meta.append(meta)
            if not isinstance(rows, list) or not rows:
                break
            print(f"  page {page}: {len(rows):,} rows  {meta['elapsed_s']}s  {meta['bytes']:,}B")
            for r in rows:
                sym = str(r.get("symbol", ""))
                # US listings only: FMP returns global symbols, suffixed with an exchange
                # ("020Y.L"). Alphabetic, unsuffixed tickers are the US common stocks.
                if not sym.isalpha() or not (1 <= len(sym) <= 5):
                    continue
                fl = r.get("floatShares")
                if isinstance(fl, (int, float)) and 0 < fl < 75_000_000:
                    floats[sym] = {"ticker": sym, "float_shares": int(fl),
                                   "outstanding": r.get("outstandingShares"),
                                   "as_of": r.get("date")}
            if len(rows) < 5000:
                break

        print(f"\n  US-looking symbols with 0 < float < 75,000,000: {len(floats):,}")

        # The test set must be the population the scanner will actually see, which is the
        # INTERSECTION of the screener pre-filter and the float cap — not simply "float is
        # small". A first attempt took the largest floats under the cap and produced 20
        # names clustered at 74.1-74.9M, nearly all foreign ADRs with avgVolume 0. Those
        # would have flattered the result: a feed can look perfect on tickers that never
        # trade. Stage 1 is `float < 75M AND volume_avg_20d > 500K`, so both halves apply.
        screened, smeta = await call(c, "company-screener", {
            "priceMoreThan": 2, "volumeMoreThan": 500_000, "isEtf": "false",
            "isFund": "false", "isActivelyTrading": "true", "country": "US", "limit": 5000,
        })
        if not isinstance(screened, list):
            print(f"  company-screener failed: {smeta.get('error') or smeta['status']}")
            return 1
        print(f"  screener (price>$2, vol>500K, US, not ETF/fund): {len(screened):,} rows"
              f"  {smeta['elapsed_s']}s  {smeta['bytes']:,}B")

        liquid = {}
        for r in screened:
            sym = str(r.get("symbol", ""))
            if sym in floats:
                liquid[sym] = {**floats[sym],
                               "price": r.get("price"),
                               "avg_volume": r.get("volume"),
                               "market_cap": r.get("marketCap"),
                               "exchange": r.get("exchangeShortName"),
                               "name": r.get("companyName")}
        print(f"  INTERSECTION (screener AND float < 75M): {len(liquid):,} — this is the "
              f"real Stage-1 universe size")

        # Ascending float: the smallest tradeable floats are the strategy's actual target
        # and the hardest case for any data feed.
        chosen = sorted(liquid.values(), key=lambda d: d["float_shares"])[:target]

    chosen.sort(key=lambda d: d["float_shares"])
    print(f"\n  Test set: {len(chosen)} names with float < 75M and price > $2")
    print(f"  {'ticker':8}{'float':>14}{'price':>10}{'avgVolume':>14}")
    for d in chosen:
        print(f"  {d['ticker']:8}{d['float_shares']:>14,}{d['price']:>10.2f}"
              f"{(d.get('avg_volume') or 0):>14,.0f}")
    write("lowfloat_set", {"chosen": chosen, "total_lowfloat_us": len(floats)},
          {"mode": "lowfloat", "pages": page_meta})
    return 0


async def mode_probe_set(session: str) -> int:
    """A.4 / A.5 — extended bars for every low-float name, plus controls."""
    doc = load("lowfloat_set")
    if not doc:
        print("  Run --lowfloat first.")
        return 1
    tickers = [d["ticker"] for d in doc["payload"]["chosen"]]
    live, now = in_premarket()
    out: dict[str, Any] = {}

    print(f"  {'ticker':8}{'bars':>6}{'pm':>5}{'earliest':>10}{'vol_sum':>12}  note")
    async with FmpClient() as c:
        for t in tickers + CONTROLS:
            bars, meta = await call(c, "historical-chart/5min",
                                    {"symbol": t, "from": session, "to": session,
                                     "extended": "true"}, symbol=t)
            out[t] = {"meta": meta, "bars": bars}
            if not isinstance(bars, list):
                print(f"  {t:8}{'-':>6}{'-':>5}{'-':>10}{'-':>12}  {meta.get('error','non-list')[:40]}")
                continue
            pm = premarket_bars(bars)
            earliest = min((bar_time(b) for b in pm), default=None)
            vsum = sum(b.get("volume") or 0 for b in pm)
            note = "EMPTY (no data)" if not bars else ("no pre-market bars" if not pm else "")
            print(f"  {t:8}{len(bars):>6}{len(pm):>5}"
                  f"{earliest.strftime('%H:%M') if earliest else '-':>10}{vsum:>12,}  {note}")

    write(f"probe_set_{now:%H%M%S}", out, {"mode": "probe_set", "session": session,
                                          "live_premarket": live, "captured_at_et": now.isoformat()})
    return 0


# ------------------------------------------------------------------ B.7 integrity series


async def mode_sample_series(minutes: int, interval: int, session: str) -> int:
    """B.7 — re-request the SAME window repeatedly. Two failure modes are being hunted:
    a cumulative series that decreases, and a historical window whose volumes change
    between identical requests."""
    doc = load("lowfloat_set")
    tickers = ([d["ticker"] for d in doc["payload"]["chosen"][:12]] if doc else []) + CONTROLS
    samples = max(1, minutes // interval + 1)
    print(f"  Sampling {len(tickers)} tickers x {samples} passes, {interval} min apart.")

    for i in range(samples):
        now = datetime.now(ET)
        snap: dict[str, Any] = {}
        async with FmpClient() as c:
            for t in tickers:
                bars, meta = await call(c, "historical-chart/5min",
                                        {"symbol": t, "from": session, "to": session,
                                         "extended": "true"}, symbol=t)
                snap[t] = {"meta": meta, "bars": bars if isinstance(bars, list) else None}
        write(f"series_{now:%Y%m%dT%H%M%S}", snap, {"mode": "series", "et": now.isoformat(),
                                                    "session": session})
        totals = {t: sum(b.get("volume") or 0 for b in premarket_bars(v["bars"] or []))
                  for t, v in snap.items()}
        print(f"  [{i+1}/{samples}] {now:%H:%M:%S} ET  " +
              "  ".join(f"{t}={totals[t]:,}" for t in tickers[:4]))
        if i < samples - 1:
            time.sleep(interval * 60)
    return 0


# ------------------------------------------------------------------ C. history depth


async def mode_history(session: str) -> int:
    """C.8 / C.9 — how far back do extended-hours intraday bars go, and are they complete
    for low-float names?"""
    doc = load("lowfloat_set")
    picks = ([d["ticker"] for d in doc["payload"]["chosen"][:3]] if doc else []) + ["AAPL"]
    today = datetime.now(ET).date()
    results = {}

    async with FmpClient() as c:
        for sym in picks:
            per_sym = {}
            for days in (10, 40, 120, 400, 1200):
                start = (today - timedelta(days=days)).isoformat()
                bars, meta = await call(c, "historical-chart/5min",
                                        {"symbol": sym, "from": start, "to": today.isoformat(),
                                         "extended": "true"}, symbol=sym)
                if not isinstance(bars, list):
                    per_sym[days] = {"meta": meta, "error": meta.get("error")}
                    print(f"  {sym:6} {days:>5}d  ERROR {meta.get('error','')[:50]}")
                    continue
                times = [t for t in (bar_time(b) for b in bars) if t]
                pm = premarket_bars(bars)
                pm_sessions = sorted({bar_time(b).date() for b in pm if bar_time(b)})
                per_sym[days] = {
                    "meta": meta, "bars": len(bars),
                    "sessions": len({t.date() for t in times}),
                    "premarket_bars": len(pm),
                    "premarket_sessions": len(pm_sessions),
                    "earliest": min(times).isoformat() if times else None,
                }
                print(f"  {sym:6} {days:>5}d  bars={len(bars):>7,}  sessions={len({t.date() for t in times}):>4}"
                      f"  pm_sessions={len(pm_sessions):>4}  earliest={min(times).date() if times else '-'}"
                      f"  {meta['bytes']:,}B  {meta['elapsed_s']}s")
            results[sym] = per_sym
    write("history_depth", results, {"mode": "history"})
    return 0


# ------------------------------------------------------------------ D/E. scale + limits


async def mode_scale() -> int:
    """D.10, D.12, E.15 — batch-quote limits, screener fields and universe sizing."""
    results: dict[str, Any] = {}
    async with FmpClient() as c:
        # D.10 — batch-quote size ceiling.
        base = load("lowfloat_set")
        pool = [d["ticker"] for d in base["payload"]["chosen"]] if base else []
        pool = (pool + CONTROLS * 200)[:1200]
        for n in (50, 100, 500, 1000):
            syms = pool[:n]
            quotes, meta = await call(c, "batch-quote", {"symbols": ",".join(syms)})
            got = len(quotes) if isinstance(quotes, list) else 0
            results[f"batch_quote_{n}"] = {"meta": meta, "requested": len(syms), "returned": got}
            print(f"  batch-quote  requested={len(syms):>5}  returned={got:>5}"
                  f"  {meta['elapsed_s']}s  {meta['bytes']:,}B  {meta.get('error','')[:40]}")
            if isinstance(quotes, list) and quotes:
                results[f"batch_quote_{n}"]["sample"] = quotes[0]

        # D.12 — screener universe sizing at several pre-filters.
        settings = [
            {"priceMoreThan": 2, "volumeMoreThan": 500000, "marketCapLowerThan": 2_000_000_000},
            {"priceMoreThan": 2, "volumeMoreThan": 500000, "marketCapLowerThan": 5_000_000_000},
            {"priceMoreThan": 2, "volumeMoreThan": 500000},
        ]
        for i, s in enumerate(settings):
            params = {**s, "limit": 5000, "isEtf": "false", "isFund": "false"}
            rows, meta = await call(c, "company-screener", params)
            n = len(rows) if isinstance(rows, list) else 0
            results[f"screener_{i}"] = {"meta": meta, "count": n,
                                        "sample": rows[0] if isinstance(rows, list) and rows else None}
            cap = s.get("marketCapLowerThan")
            print(f"  screener  cap={'none' if not cap else f'${cap/1e9:.0f}B':>6}  rows={n:>6}"
                  f"  {meta['elapsed_s']}s  {meta['bytes']:,}B")
            if isinstance(rows, list) and rows:
                print(f"            fields: {sorted(rows[0].keys())}")
    write("scale", results, {"mode": "scale"})
    return 0


# ------------------------------------------------------------------ fixtures


async def mode_fixtures(session: str) -> int:
    """Record the new Premium endpoint shapes for offline replay. CI never calls FMP.

    Large collection payloads are recorded as a bounded slice: `shares-float-all` and
    `company-screener` are ~0.7 MB each per page, and the value of a fixture is the SHAPE
    of a row, not 5,000 of them. The slice size is recorded in the note so nobody mistakes
    a truncated fixture for a full page.
    """
    from app.services.fmp.fixtures import FixtureStore

    store = FixtureStore()
    doc = load("lowfloat_set")
    active = doc["payload"]["chosen"][0]["ticker"] if doc else "AAPL"
    # A ticker that returned an empty array earlier — the "no pre-market activity" branch,
    # which the scanner must distinguish from an outage and which therefore needs a fixture.
    quiet = "EROC"

    recorded = []
    async with FmpClient() as c:
        targets = [
            ("historical-chart/5min",
             {"symbol": "AAPL", "from": session, "to": session, "extended": "true"}, None, "megacap"),
            ("historical-chart/5min",
             {"symbol": active, "from": session, "to": session, "extended": "true"}, None, "low-float active"),
            ("historical-chart/5min",
             {"symbol": quiet, "from": session, "to": session, "extended": "true"}, None, "no pre-market activity"),
            ("historical-chart/1min",
             {"symbol": "AAPL", "from": session, "to": session, "extended": "true"}, None, "1min extended"),
            ("batch-quote", {"symbols": "AAPL,MSFT,NVDA"}, None, "batch-quote"),
            ("shares-float-all", {"limit": 5000, "page": 0}, 25, "bulk float, first 25 rows only"),
            ("company-screener",
             {"priceMoreThan": 2, "volumeMoreThan": 500_000, "isEtf": "false", "isFund": "false",
              "isActivelyTrading": "true", "country": "US", "limit": 5000}, 25,
             "screener, first 25 rows only"),
        ]
        for endpoint, params, slice_n, note in targets:
            payload, meta = await call(c, endpoint, params)
            if meta.get("error"):
                print(f"  {endpoint:28} SKIPPED — {meta['error'][:60]}")
                continue
            body = payload
            full_rows = len(body) if isinstance(body, list) else None
            if slice_n and isinstance(body, list):
                body = body[:slice_n]
                note = f"{note} (sliced from {full_rows} rows)"
            path = store.save(endpoint, params, meta["status"], body, note=note)
            recorded.append(path.name)
            print(f"  {endpoint:28} -> {path.name[:58]}  ({path.stat().st_size:,}B)")
    print(f"\n  {len(recorded)} fixture(s) recorded under {store.root}")
    return 0


# ------------------------------------------------------------------ offline analysis


def mode_analyse(session: str) -> int:
    """B.7 verdict + A.3 confirmation, from stored series. 0 API calls."""
    files = sorted(OUT.glob("series_*.json"))
    if not files:
        print(f"  No series files in {OUT}. Run --sample-series first.")
        return 1

    per_ticker: dict[str, list] = {}
    window_hashes: dict[str, set] = {}
    for f in files:
        doc = json.loads(f.read_text(encoding="utf-8"))
        clock = doc["meta"]["et"][11:19]
        for t, v in doc["payload"].items():
            bars = v.get("bars") or []
            pm = premarket_bars(bars)
            total = sum(b.get("volume") or 0 for b in pm)
            per_ticker.setdefault(t, []).append((clock, total, len(pm)))
            # Reproducibility: volumes of bars strictly BEFORE the last one should never
            # change between requests. The final bar is still forming, so it is excluded.
            closed = sorted(pm, key=lambda b: bar_time(b))[:-1]
            sig = tuple((b["date"], b.get("volume")) for b in closed)
            window_hashes.setdefault(t, set()).add(sig[:len(sig)])

    print(f"  Read {len(files)} series snapshot(s) — 0 API calls\n")
    print(f"  {'ticker':8}{'verdict':<30}series of summed pre-market volume")
    problems = []
    for t, pts in per_ticker.items():
        totals = [x[1] for x in pts]
        deltas = [b - a for a, b in zip(totals, totals[1:])]
        if any(d < 0 for d in deltas):
            verdict = "DECREASED (integrity fault)"
            problems.append(t)
        elif totals[-1] > totals[0]:
            verdict = "accumulates"
        elif all(v == 0 for v in totals):
            verdict = "no pre-market volume"
        else:
            verdict = "flat (no trades in window)"
        rendered = " ".join(f"{c[:5]}={v:,}" for c, v, _ in pts)
        print(f"  {t:8}{verdict:<30}{rendered}")

    print("\n  Reproducibility of CLOSED bars across identical re-requests:")
    unstable = [t for t, sigs in window_hashes.items() if len(sigs) > 1]
    if unstable:
        print(f"    UNSTABLE for {len(unstable)}: {', '.join(unstable)}")
        print("    The same historical window returned different volumes on re-request.")
    else:
        print(f"    Stable for all {len(window_hashes)} tickers — closed bars never changed.")

    print(f"\n  Decreasing cumulative totals: {problems if problems else 'none'}")
    write("analysis", {"per_ticker": per_ticker,
                       "unstable_windows": unstable,
                       "decreasing": problems}, {"mode": "analyse", "files": len(files)})
    return 0


# ----------------------------------------------------------------------------- entry


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 4A FMP Premium probe (throwaway).")
    p.add_argument("--extended", action="store_true")
    p.add_argument("--lowfloat", action="store_true")
    p.add_argument("--probe-set", action="store_true")
    p.add_argument("--sample-series", action="store_true")
    p.add_argument("--history", action="store_true")
    p.add_argument("--scale", action="store_true")
    p.add_argument("--fixtures", action="store_true")
    p.add_argument("--analyse", action="store_true")
    p.add_argument("--minutes", type=int, default=60)
    p.add_argument("--interval", type=int, default=5)
    p.add_argument("--target", type=int, default=20, help="size of the low-float test set")
    p.add_argument("--max-pages", type=int, default=8)
    p.add_argument("--session", help="Session date YYYY-MM-DD (default: today ET)")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.WARNING,
                        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("fmp_premium_probe").setLevel(logging.INFO)
    OUT.mkdir(parents=True, exist_ok=True)

    live, now = in_premarket()
    session = args.session or now.date().isoformat()
    print(f"\n  ET {now:%Y-%m-%d %H:%M:%S} — "
          f"{'INSIDE' if live else 'OUTSIDE'} the 04:00-09:30 pre-market window; session={session}")

    async def run() -> int:
        try:
            if args.extended:
                return await mode_extended(session)
            if args.lowfloat:
                return await mode_lowfloat(args.target, args.max_pages)
            if args.probe_set:
                return await mode_probe_set(session)
            if args.sample_series:
                return await mode_sample_series(args.minutes, args.interval, session)
            if args.history:
                return await mode_history(session)
            if args.scale:
                return await mode_scale()
            if args.fixtures:
                return await mode_fixtures(session)
            p.print_help()
            return 1
        finally:
            from app.core.database import close_db
            await close_db()

    if args.analyse:
        return mode_analyse(session)
    return asyncio.run(run())


if __name__ == "__main__":
    raise SystemExit(main())
