"""Phase 4A-T — throwaway probe of Tiingo's consolidated equity intraday feed.

    uv run python scripts/probe_tiingo.py --snapshot-all
    uv run python scripts/probe_tiingo.py --tickers AAPL,TSLA
    uv run python scripts/probe_tiingo.py --historical AAPL --days 30
    uv run python scripts/probe_tiingo.py --sample-series --minutes 60 --interval 5
    uv run python scripts/probe_tiingo.py --analyse          # offline, 0 calls
    uv run python scripts/probe_tiingo.py --pick-lowfloat    # spends FMP budget

THIS IS A MEASUREMENT EXERCISE, NOT AN INTEGRATION. Nothing here is imported by `app/`,
nothing is wired into `app/config.py`, and deleting this file plus `docs/TIINGO_*.md` and
`probe_output/` removes the whole phase. See `docs/PROMPT.md` Phase 4A-T.

Two design choices are worth stating because they shape every number this produces:

1. **The whole-market snapshot is the unit of sampling.** `/tiingo/equity/intraday/` with
   no ticker returns every ticker Tiingo knows in ONE request (~4 MB). At 50 requests/hour
   on the free tier, per-ticker polling of 13 names for an hour would cost 156 calls and be
   impossible; one snapshot per interval costs 12 and covers everything at once.

2. **Raw snapshots are persisted, analysis happens offline.** The pre-market window is
   90 minutes wide and does not come back until tomorrow. So the sampler commits nothing
   to a ticker list — it stores full payloads, and `--analyse` reconstructs any ticker's
   series afterwards. Choosing the low-float test set does not block sampling.

The token comes from TIINGO_API_KEY (environment, else backend/.env). It is never logged.
"""

import argparse
import gzip
import json
import logging
import re
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx

BASE = "https://api.tiingo.com/tiingo/equity/intraday"
OUT = Path(__file__).resolve().parent.parent / "probe_output" / "tiingo"
CALLS_FILE = OUT / "_calls.json"
ET = ZoneInfo("America/New_York")

# Free tier: 50 requests/hour, 1,000/day, 1 GB/month, 500 unique symbols/month.
# The ceiling sits below 50 deliberately — the same reasoning as FMP_DAILY_BUDGET=230
# against a 250 cap. A probe that exhausts the limit cannot be re-run to check a surprise.
HOURLY_CEILING = 42

log = logging.getLogger("tiingo_probe")


# ----------------------------------------------------------------- token + rate limiting


def _token() -> str:
    import os

    token = os.environ.get("TIINGO_API_KEY")
    if not token:
        from dotenv import dotenv_values

        env = Path(__file__).resolve().parent.parent / ".env"
        token = (dotenv_values(env) or {}).get("TIINGO_API_KEY")
    if not token:
        raise SystemExit(
            "TIINGO_API_KEY is not set. Add it to backend/.env or the environment. "
            "It is probe-only and deliberately not part of app/config.py."
        )
    return token


def _recent_calls() -> list[float]:
    """Call timestamps inside the trailing hour."""
    if not CALLS_FILE.exists():
        return []
    try:
        stamps = json.loads(CALLS_FILE.read_text())
    except json.JSONDecodeError:
        return []
    cutoff = time.time() - 3600
    return [t for t in stamps if t > cutoff]


def _record_call() -> None:
    stamps = _recent_calls() + [time.time()]
    CALLS_FILE.write_text(json.dumps(stamps))


def budget_remaining() -> int:
    return HOURLY_CEILING - len(_recent_calls())


def _spend(n: int = 1) -> None:
    """Stop cleanly rather than tripping Tiingo's own limiter."""
    if budget_remaining() < n:
        oldest = min(_recent_calls())
        wait = int(3600 - (time.time() - oldest))
        raise SystemExit(
            f"Local hourly ceiling reached ({HOURLY_CEILING} calls in the trailing hour). "
            f"Partial results are preserved in {OUT}. Roughly {wait // 60} min until the "
            f"window slides. Raise HOURLY_CEILING only if you have checked Tiingo's own "
            f"50/hour limit has room."
        )


def get(path: str, params: dict[str, Any] | None = None, timeout: int = 120) -> tuple[Any, dict]:
    """One measured GET. Returns (parsed, meta) where meta carries the probe evidence."""
    _spend()
    url = f"{BASE}{path}" if path else f"{BASE}/"
    headers = {"Authorization": f"Token {_token()}", "Content-Type": "application/json"}

    started = time.time()
    resp = httpx.get(url, headers=headers, params=params, timeout=timeout,
                     follow_redirects=True)
    elapsed = time.time() - started
    _record_call()

    meta = {
        "url": str(resp.url).split("token=")[0],
        "status": resp.status_code,
        "elapsed_s": round(elapsed, 2),
        "bytes": len(resp.content),
        "requested_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    log.info("GET %s -> %s  %.2fs  %s bytes", path or "/", resp.status_code, elapsed,
             f"{len(resp.content):,}")

    if resp.status_code != 200:
        meta["body"] = resp.text[:1000]
        return None, meta
    try:
        return resp.json(), meta
    except json.JSONDecodeError:
        meta["body"] = resp.text[:1000]
        return None, meta


def _write(name: str, payload: Any, meta: dict, gzipped: bool = False) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    doc = {"meta": meta, "payload": payload}
    if gzipped:
        path = OUT / f"{name}.json.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            json.dump(doc, fh)
    else:
        path = OUT / f"{name}.json"
        path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    log.info("  wrote %s (%s bytes on disk)", path.name, f"{path.stat().st_size:,}")
    return path


# ----------------------------------------------------------------- snapshot analysis


_FRACTION = re.compile(r"\.(\d+)")


def parse_ts(ts: str | None) -> datetime | None:
    """Parse a Tiingo timestamp, tolerating NANOSECOND precision.

    Tiingo returns nine fractional digits ("04:16:32.645031618-04:00"). Python 3.10's
    `datetime.fromisoformat` accepts only three or six and raises on anything else — so the
    naive version of this function silently classified 6,386 of 8,685 US rows as
    "unparseable timestamp", which read as "stale" and made the feed look far worse than it
    is. Truncate to microseconds instead of trusting the stdlib parser.

    The historical endpoint adds a second quirk: it ends timestamps with "Z"
    ("2026-06-25T13:30:00.000Z"), which 3.10 also rejects. Both are normalised here.
    """
    if not ts:
        return None
    if ts.endswith(("Z", "z")):
        ts = f"{ts[:-1]}+00:00"
    m = _FRACTION.search(ts)
    if m and len(m.group(1)) not in (3, 6):
        ts = f"{ts[:m.start()]}.{m.group(1)[:6]:0<6}{ts[m.end():]}"
    try:
        return datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return None


def _is_fresh(row: dict, session_date) -> bool:
    """Does this row carry data from the session we are actually in?

    The single most important discriminator in the whole probe. A row can be present,
    well-formed and carry a plausible volume while being a stale copy of a close from days
    ago — which for a live scanner is worse than an absent row, because it looks usable.
    """
    parsed = parse_ts(row.get("timestamp"))
    return parsed is not None and parsed.astimezone(ET).date() == session_date


def summarise_snapshot(rows: list[dict], session_date) -> dict:
    fresh = [r for r in rows if _is_fresh(r, session_date)]
    with_vol = [r for r in rows if r.get("volume") is not None]
    fresh_with_vol = [r for r in fresh if r.get("volume") is not None]

    # US-listed names are alphabetic; the feed also carries numeric foreign codes.
    us_like = [r for r in rows if str(r.get("ticker", "")).isalpha()]

    dates: dict[str, int] = {}
    for r in rows:
        ts = r.get("timestamp")
        if ts:
            try:
                d = parse_ts(ts).astimezone(ET).date().isoformat()
                dates[d] = dates.get(d, 0) + 1
            except (ValueError, TypeError):
                pass

    return {
        "tickers_total": len(rows),
        "ticker_alphabetic_us_like": len(us_like),
        "volume_non_null": len(with_vol),
        "fresh_today": len(fresh),
        "fresh_today_with_volume": len(fresh_with_vol),
        "pct_fresh": round(100 * len(fresh) / len(rows), 2) if rows else 0,
        "pct_volume_non_null": round(100 * len(with_vol) / len(rows), 2) if rows else 0,
        "timestamp_dates_top": dict(sorted(dates.items(), key=lambda kv: -kv[1])[:8]),
    }


# ----------------------------------------------------------------- modes


def mode_snapshot_all(session_date) -> int:
    """C.7 / C.8 — the whole-market snapshot: size, latency, coverage, freshness."""
    rows, meta = get("/")
    if rows is None:
        print(f"[FAIL] snapshot-all: HTTP {meta['status']}\n{meta.get('body','')}")
        _write(f"snapshot_FAILED_{int(time.time())}", None, meta)
        return 1

    summary = summarise_snapshot(rows, session_date)
    meta["summary"] = summary
    stamp = datetime.now(ET).strftime("%Y%m%dT%H%M%S")
    _write(f"snapshot_{stamp}", rows, meta, gzipped=True)

    print(f"\n  Whole-market snapshot  ({meta['elapsed_s']}s, {meta['bytes']:,} bytes)")
    for k, v in summary.items():
        print(f"    {k:32} {v}")
    print(f"\n  Local hourly budget remaining: {budget_remaining()}/{HOURLY_CEILING}")
    return 0


def mode_sample_series(minutes: int, interval: int, session_date) -> int:
    """A.2 — does volume accumulate? Sampled via whole-market snapshots.

    Each sample is a full snapshot, so every ticker's series is captured whether or not we
    had decided to care about it yet. `--analyse` reads these back.
    """
    samples = max(1, minutes // interval + 1)
    need = samples
    if budget_remaining() < need:
        samples = budget_remaining()
        log.warning("Budget allows only %s samples, not %s. Shortening the run.",
                    samples, need)
    print(f"  Sampling {samples} whole-market snapshots, {interval} min apart "
          f"(~{(samples - 1) * interval} min of coverage). "
          f"Budget after: {budget_remaining() - samples}/{HOURLY_CEILING}")

    for i in range(samples):
        now_et = datetime.now(ET)
        rows, meta = get("/")
        if rows is None:
            log.error("sample %s failed: HTTP %s", i + 1, meta["status"])
            _write(f"series_FAILED_{now_et.strftime('%Y%m%dT%H%M%S')}", None, meta)
        else:
            meta["summary"] = summarise_snapshot(rows, session_date)
            meta["et_time"] = now_et.isoformat()
            _write(f"series_{now_et.strftime('%Y%m%dT%H%M%S')}", rows, meta, gzipped=True)
            s = meta["summary"]
            print(f"  [{i+1}/{samples}] {now_et:%H:%M:%S ET}  "
                  f"tickers={s['tickers_total']:,}  fresh_today={s['fresh_today']:,}  "
                  f"fresh+vol={s['fresh_today_with_volume']:,}  {meta['elapsed_s']}s")
        if i < samples - 1:
            time.sleep(interval * 60)
    return 0


def mode_tickers(tickers: list[str]) -> int:
    """A.1 / B — the per-ticker endpoint, raw payload per name."""
    results = {}
    for t in tickers:
        if budget_remaining() < 1:
            log.warning("Budget exhausted; stopping after %s tickers.", len(results))
            break
        rows, meta = get(f"/{t}")
        results[t] = {"meta": meta, "rows": rows}
        if rows:
            r = rows[0] if isinstance(rows, list) and rows else {}
            print(f"  {t:6} ts={r.get('timestamp')}  last={r.get('tngoLast')}  "
                  f"vol={r.get('volume')}  prevClose={r.get('prevClose')}")
        else:
            print(f"  {t:6} HTTP {meta['status']}  {meta.get('body', '')[:120]}")
    _write(f"tickers_{datetime.now(ET):%Y%m%dT%H%M%S}", results, {"mode": "tickers"})
    return 0


def mode_historical(ticker: str, days: int) -> int:
    """D — historical intraday with opt-in volume, and how far back it reaches."""
    start = (datetime.now(ET) - timedelta(days=days)).date().isoformat()
    params = {
        "startDate": start,
        "resampleFreq": "5min",
        "columns": "open,high,low,close,volume",
        "afterHours": "true",
    }
    rows, meta = get(f"/{ticker}/prices", params=params)
    meta["params"] = params
    if rows is None:
        print(f"  [FAIL] historical {ticker}: HTTP {meta['status']}\n{meta.get('body','')}")
        _write(f"historical_{ticker}_FAILED", None, meta)
        return 1

    stamps = []
    for r in rows:
        try:
            parsed = parse_ts(r.get("date"))
            if parsed is not None:
                stamps.append(parsed.astimezone(ET))
        except (ValueError, TypeError, KeyError):
            pass
    premarket = [s for s in stamps if (4, 0) <= (s.hour, s.minute) < (9, 30)]
    sessions = sorted({s.date() for s in stamps})
    pm_sessions = sorted({s.date() for s in premarket})
    has_vol = [r for r in rows if r.get("volume") is not None]

    meta["analysis"] = {
        "bars": len(rows),
        "bars_with_volume": len(has_vol),
        "earliest": min(stamps).isoformat() if stamps else None,
        "latest": max(stamps).isoformat() if stamps else None,
        "distinct_sessions": len(sessions),
        "premarket_bars": len(premarket),
        "sessions_with_premarket_bars": len(pm_sessions),
        "earliest_premarket_clock_et": (
            min(f"{s.hour:02d}:{s.minute:02d}" for s in premarket) if premarket else None
        ),
        "requested_days_back": days,
    }
    _write(f"historical_{ticker}_{days}d", rows, meta)
    print(f"\n  Historical intraday — {ticker}, requested {days} days back")
    for k, v in meta["analysis"].items():
        print(f"    {k:32} {v}")
    return 0


def mode_analyse(watch: list[str], session_date) -> int:
    """Offline. Rebuilds per-ticker volume series from the stored snapshots. 0 API calls."""
    files = sorted(OUT.glob("series_*.json.gz")) + sorted(OUT.glob("snapshot_*.json.gz"))
    if not files:
        print(f"  No stored snapshots in {OUT}. Run --sample-series first.")
        return 1

    series: dict[str, list[tuple[str, Any, Any]]] = {t: [] for t in watch}
    snapshot_stats = []
    for path in files:
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            doc = json.load(fh)
        rows, meta = doc["payload"], doc["meta"]
        if not rows:
            continue
        et_time = meta.get("et_time") or meta.get("requested_at_utc", "")
        clock = et_time[11:19]
        # Recomputed here, never read from meta["summary"]. Samples captured before the
        # nanosecond-timestamp fix carry summaries that undercount freshness by ~400x.
        snapshot_stats.append((clock, summarise_snapshot(rows, session_date), meta))
        index = {str(r.get("ticker", "")).upper(): r for r in rows}
        for t in watch:
            r = index.get(t.upper())
            if r is None:
                series[t].append((clock, None, "ABSENT"))
            else:
                series[t].append((clock, r.get("volume"),
                                  "fresh" if _is_fresh(r, session_date) else "STALE"))

    print(f"\n  Read {len(files)} stored snapshot(s) — 0 API calls\n")
    print("  Snapshot-level coverage over time")
    print(f"    {'ET':10} {'tickers':>8} {'fresh':>8} {'fresh+vol':>10} {'bytes':>12}")
    for clock, s, meta in snapshot_stats:
        print(f"    {clock:10} {s.get('tickers_total', 0):>8,} {s.get('fresh_today', 0):>8,} "
              f"{s.get('fresh_today_with_volume', 0):>10,} {meta.get('bytes', 0):>12,}")

    print("\n  Per-ticker volume series (A.2 / B.5)")
    verdicts = {}
    for t in watch:
        pts = series[t]
        vols = [(c, v) for c, v, st in pts if v is not None and st == "fresh"]
        rendered = " ".join(f"{c[:5]}={v:,}" if v is not None else f"{c[:5]}=-"
                            for c, v, _ in pts)
        # A flat series is NOT evidence against cumulative volume. For a thin small cap that
        # simply did not trade between two samples, an unchanged cumulative total is the
        # correct reading — the failure mode we are looking for is a value that FALLS or
        # oscillates, which is what a per-transaction size field would do. Conflating
        # "idle" with "not accumulating" would condemn exactly the tickers this strategy
        # targets, so the two are reported separately.
        if not vols:
            states = {st for _, _, st in pts}
            verdict = "ABSENT" if states == {"ABSENT"} else "no fresh volume"
        elif len(vols) < 2:
            verdict = "single sample"
        else:
            vals = [v for _, v in vols]
            deltas = [b - a for a, b in zip(vals, vals[1:])]
            if any(d < 0 for d in deltas):
                verdict = "DECREASING (not cumulative)"
            elif vals[-1] > vals[0]:
                verdict = "CUMULATIVE (rises)"
            elif vals[-1] == 0:
                verdict = "IDLE at zero (no trades yet)"
            else:
                verdict = "IDLE (flat, no trades in window)"
        verdicts[t] = verdict
        print(f"    {t:6} {verdict:28} {rendered}")

    print("\n  Verdict tally")
    tally: dict[str, int] = {}
    for v in verdicts.values():
        key = v.split(" (")[0]
        tally[key] = tally.get(key, 0) + 1
    for k, v in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"    {k:32} {v}")

    (OUT / "analysis.json").write_text(
        json.dumps({"series": series, "verdicts": verdicts,
                    "snapshots": [(c, s) for c, s, _ in snapshot_stats]}, indent=2),
        encoding="utf-8")
    return 0


def mode_pick_lowfloat(limit: int, session_date) -> int:
    """B.4 — build a REAL, float-verified low-float test set. Never guessed from memory.

    Candidates come from Tiingo's own live snapshot (tickers observed trading in this
    pre-market session), and their floats are then verified through the existing FMP client
    and its budget guard.

    A finding worth recording separately: `shares-float` is NOT restricted to the free
    tier's ~43-symbol quote sample. It returns real floats for arbitrary small caps, which
    is what makes this test set possible at all — and it has implications well beyond this
    probe. `reference_data` holds only megacaps because the universe was built from `quote`
    accessibility, not because float was unavailable.
    """
    import asyncio

    from _bootstrap import run_cli  # noqa: F401  (path setup for app.* imports)

    async def _pick() -> int:
        from app.services.fmp.client import FmpClient

        files = sorted(OUT.glob("series_*.json.gz")) + sorted(OUT.glob("snapshot_*.json.gz"))
        if not files:
            print("  No stored snapshot. Run --snapshot-all or --sample-series first.")
            return 1
        with gzip.open(files[-1], "rt", encoding="utf-8") as fh:
            rows = json.load(fh)["payload"]

        universe_file = OUT / "supported_us_stocks.json"
        if not universe_file.exists():
            print(f"  Missing {universe_file.name} — fetch Tiingo's supported-ticker list.")
            return 1
        us = {x["ticker"].upper() for x in json.loads(universe_file.read_text())}

        # Observed trading in THIS session, US common stock, at or above the strategy's
        # $2 price floor. Ascending price: low-float names skew small and cheap, so this
        # spends the FMP budget where the hit rate is highest.
        candidates = [
            r for r in rows
            if str(r.get("ticker", "")).upper() in us
            and _is_fresh(r, session_date)
            and (r.get("volume") or 0) > 0
            and (r.get("prevClose") or 0) >= 2.0
        ]
        candidates.sort(key=lambda r: r.get("prevClose") or 0)
        print(f"  Fresh, trading, >= $2 US common stock in the snapshot: {len(candidates)}")
        print(f"  Verifying float for up to {limit} of them via FMP...\n")

        verified, checked = [], 0
        async with FmpClient() as client:
            for row in candidates[:limit]:
                ticker = str(row["ticker"]).upper()
                checked += 1
                try:
                    sf = await client.get_shares_float(ticker)
                    fl = getattr(sf, "float_shares", None)
                except Exception as exc:  # probe: any failure is a datum, not a crash
                    print(f"    {ticker:8} {type(exc).__name__}: {str(exc)[:70]}")
                    continue
                if not fl:
                    continue
                entry = {
                    "ticker": ticker, "float_shares": int(fl),
                    "prev_close": row.get("prevClose"),
                    "premarket_volume_at_selection": row.get("volume"),
                    "low_float": int(fl) < 75_000_000,
                }
                verified.append(entry)
                flag = "LOW-FLOAT" if entry["low_float"] else ""
                print(f"    {ticker:8} float={int(fl):>15,}  ${row.get('prevClose'):>8.2f}  {flag}")

        low = [v for v in verified if v["low_float"]]
        print(f"\n  Checked {checked}, floats returned for {len(verified)}, "
              f"float < 75,000,000: {len(low)}")
        if verified:
            fl = [v["float_shares"] for v in verified]
            print(f"  smallest {min(fl):,}   median {statistics.median(fl):,.0f}")
        (OUT / "lowfloat_candidates.json").write_text(
            json.dumps({"checked": checked, "verified": verified, "low_float": low}, indent=2),
            encoding="utf-8")
        print(f"\n  Saved {len(low)} low-float names to lowfloat_candidates.json")
        if low:
            print("  Watch list: " + ",".join(v["ticker"] for v in low))
        return 0

    OUT.mkdir(parents=True, exist_ok=True)
    return asyncio.run(_pick())


# ----------------------------------------------------------------- entry point


def main() -> int:
    p = argparse.ArgumentParser(description="Phase 4A-T Tiingo probe (throwaway).")
    p.add_argument("--snapshot-all", action="store_true")
    p.add_argument("--tickers")
    p.add_argument("--historical", metavar="TICKER")
    p.add_argument("--days", type=int, default=30)
    p.add_argument("--sample-series", action="store_true")
    p.add_argument("--minutes", type=int, default=60)
    p.add_argument("--interval", type=int, default=5)
    p.add_argument("--analyse", action="store_true")
    p.add_argument("--watch", help="Comma-separated tickers for --analyse")
    p.add_argument("--pick-lowfloat", action="store_true")
    p.add_argument("--limit", type=int, default=25)
    p.add_argument("--budget", action="store_true", help="Show local hourly budget, 0 calls")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S",
    )
    OUT.mkdir(parents=True, exist_ok=True)

    now_et = datetime.now(ET)
    session_date = now_et.date()
    in_premarket = now_et.weekday() < 5 and (4, 0) <= (now_et.hour, now_et.minute) < (9, 30)
    print(f"\n  Now: {now_et:%Y-%m-%d %H:%M:%S %Z} — "
          f"{'INSIDE' if in_premarket else 'OUTSIDE'} the 04:00-09:30 ET pre-market window")
    if not in_premarket:
        print("  Live-session questions (A, B) cannot be answered from this sample.")

    if args.budget:
        print(f"  Local hourly budget: {budget_remaining()}/{HOURLY_CEILING} remaining")
        return 0
    if args.pick_lowfloat:
        return mode_pick_lowfloat(args.limit, session_date)
    if args.analyse:
        watch = [t.strip().upper() for t in (args.watch or "").split(",") if t.strip()]
        if not watch:
            print("  --analyse needs --watch AAPL,TSLA,...")
            return 1
        return mode_analyse(watch, session_date)
    if args.snapshot_all:
        return mode_snapshot_all(session_date)
    if args.sample_series:
        return mode_sample_series(args.minutes, args.interval, session_date)
    if args.tickers:
        return mode_tickers([t.strip().upper() for t in args.tickers.split(",") if t.strip()])
    if args.historical:
        return mode_historical(args.historical.upper(), args.days)

    p.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
