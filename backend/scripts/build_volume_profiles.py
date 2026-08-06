"""Build pre-market volume profiles — the denominator for normalized RVOL.

    uv run python scripts/build_volume_profiles.py --limit 20
    uv run python scripts/build_volume_profiles.py --tickers FFAI,ASTC --force
    uv run python scripts/build_volume_profiles.py --show          # 0 calls

Profiles are built for the **Stage-1 eligible** set, not the whole maintained universe: at
roughly 4 calls per ticker, profiling every maintained ticker would spend ~16,000 calls a
night producing denominators for names the scanner never reaches Stage 2 with.

Re-running the same day is a no-op per ticker unless `--force` is given, which is what makes
the nightly cost incremental rather than a full rebuild.
"""

import argparse
import time

# Import first: puts the backend directory on sys.path for the `app.*` imports below.
from _bootstrap import configure_logging, run_cli

from app.services.fmp.client import FmpClient
from app.services.reference.volume_profile import (
    STATUS_BUILT,
    STATUS_FAILED,
    STATUS_NO_DATA,
    STATUS_SKIPPED,
    STATUS_THIN,
    VolumeProfileBuilder,
)


async def build(args: argparse.Namespace) -> int:
    client = FmpClient()
    builder = VolumeProfileBuilder(client, force=args.force)

    try:
        if args.tickers:
            tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        else:
            tickers = await builder.stage1_tickers(limit=args.limit)
            if not tickers:
                print("\n  No Stage-1 eligible tickers. Run build_universe.py and "
                      "refresh_reference_data.py first.")
                return 1

        bytes_before = await client.budget.bytes_used_today()
        print(f"\n  Building profiles for {len(tickers)} ticker(s); "
              f"~{builder._settings.profile_sessions_target} sessions each, "
              f"fetched {builder._settings.profile_fetch_days_per_request} days per request.")

        started = time.monotonic()
        report = await builder.run(tickers)
        elapsed = time.monotonic() - started

        # Attributed per ticker, NOT taken from the global counter delta: the nightly
        # refresh may be running concurrently and would inflate it.
        calls = report.calls_used
        used_bytes = await client.budget.bytes_used_today() - bytes_before
        bw = await client.budget.bandwidth_status()

        print(f"\n  {'ticker':<9}{'status':<10}{'sessions':>9}{'buckets':>9}{'calls':>7}  detail")
        for r in report.results:
            print(f"  {r.ticker:<9}{r.status:<10}{r.sessions:>9}{r.buckets:>9}{r.calls_used:>7}"
                  f"  {r.detail[:52]}")

        print()
        for status in (STATUS_BUILT, STATUS_THIN, STATUS_SKIPPED, STATUS_NO_DATA, STATUS_FAILED):
            n = report.count(status)
            if n:
                print(f"    {status:<12}: {n}")
        print(f"\n  calls used   : {calls:,}")
        print(f"  bytes used   : {used_bytes:,}  (global delta; includes any concurrent job)")
        print(f"  wall time    : {elapsed:.1f}s")
        print(f"  bandwidth 30d: {bw['bytes_30d'] / 1e9:.2f} GB of "
              f"{bw['allowance_bytes'] / 1e9:.0f} GB ({bw['pct_used']}%)")

        if report.thin:
            print(f"\n  [WARNING] {len(report.thin)} profile(s) built from fewer than "
                  f"{builder._settings.profile_sessions_min} sessions. RVOL divides by these, "
                  f"so a thin profile produces a confident-looking but noisy number:")
            for r in report.thin:
                print(f"      {r.ticker:<8} {r.sessions} session(s)")

        if report.stopped_early:
            print(f"\n  STOPPED EARLY: {report.stop_reason}")
            print("  Completed profiles are committed; re-run to continue.")
        return 2 if report.count(STATUS_FAILED) else 0
    finally:
        await client.aclose()


async def show(limit: int) -> int:
    from sqlalchemy import func, select

    from app.core.database import async_session_maker
    from app.models.premarket_volume_profile import PremarketVolumeProfile as P

    async with async_session_maker() as db:
        tickers = await db.scalar(select(func.count(func.distinct(P.ticker))))
        rows = await db.scalar(select(func.count()).select_from(P))
        summary = (await db.execute(
            select(P.ticker, func.max(P.sessions_sampled), func.count(),
                   func.max(P.avg_cumulative_volume), func.max(P.computed_at))
            .group_by(P.ticker).order_by(P.ticker).limit(limit)
        )).all()

    print(f"\n  profiled tickers: {tickers or 0:,}   rows: {rows or 0:,}")
    if summary:
        print(f"\n  {'ticker':<9}{'sessions':>9}{'buckets':>9}{'peak avg cum vol':>19}  built")
        for t, sessions, buckets, peak, when in summary:
            print(f"  {t:<9}{sessions:>9}{buckets:>9}{peak:>19,.0f}  {when:%Y-%m-%d %H:%M}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build pre-market volume profiles.")
    parser.add_argument("--tickers", help="Comma-separated tickers (default: Stage-1 set)")
    parser.add_argument("--limit", type=int, help="Process at most N tickers")
    parser.add_argument("--force", action="store_true", help="Rebuild even if built today")
    parser.add_argument("--show", action="store_true", help="Read back profiles (0 calls)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)

    raise SystemExit(run_cli(show(args.limit or 20) if args.show else build(args)))
