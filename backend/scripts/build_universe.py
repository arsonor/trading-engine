"""Build the Stage-1 universe from live FMP Premium data.

    uv run python scripts/build_universe.py
    uv run python scripts/build_universe.py --dry-run
    uv run python scripts/build_universe.py --show          # read back, 0 calls

A separate CLI rather than a flag on `refresh_reference_data.py`, deliberately: the two
jobs have different costs, different failure modes and different reasons to be re-run.
Building the universe is ~9 calls and answers "which tickers exist"; refreshing reference
data is one call per surviving ticker and answers "what are their numbers". Running the
second without the first is normal (nothing has been listed or delisted mid-morning);
running the first without the second leaves a universe with no metrics. Folding them into
one command would make the cheap, safe half impossible to run on its own.

Cost: one `company-screener` call plus ~8 `shares-float-all` pages.
"""

import argparse

# Import first: puts the backend directory on sys.path for the `app.*` imports below.
from _bootstrap import configure_logging, run_cli

from app.services.reference.universe_builder import UniverseBuilder


async def build(dry_run: bool) -> int:
    from app.services.fmp.client import FmpClient

    builder = UniverseBuilder()

    if dry_run:
        # Still costs the same calls — the point is to see the outcome without writing.
        async with FmpClient() as client:
            rows = await builder.screen(client)
            floats = await builder.bulk_floats(client)
        cap = builder._settings.scan_float_max
        with_float = [r for r in rows if floats.get(str(r["symbol"]).upper())]
        passing = [r for r in with_float if floats[str(r["symbol"]).upper()] < cap]
        print("\n  DRY RUN — nothing written")
        print(f"  screener rows           : {len(rows):,}")
        print(f"  float known             : {len(with_float):,}")
        print(f"  float < {cap:,}   : {len(passing):,}  <- would be the universe")
        print(f"  sample: {', '.join(sorted(str(r['symbol']) for r in passing)[:15])}")
        return 0

    report = await builder.build()

    print(f"\n  Universe build (run {report.run_id})")
    print(f"  {'screener pre-filter':<26}{report.screener_count:>8,}")
    print(f"  {'bulk float rows':<26}{report.float_rows:>8,}")
    print(f"  {'no float available':<26}{report.without_float:>8,}")
    print(f"  {'dropped by float cap':<26}{report.dropped_by_float_cap:>8,}")
    print(f"  {'MAINTAINED UNIVERSE':<26}{report.universe_size:>8,}   (reference_data kept for these)")
    eligible = "n/a (no reference_data yet)" if report.stage1_eligible is None else f"{report.stage1_eligible:,}"
    print(f"  {'clears Stage 1 today':<26}{eligible:>8}   (what each live pass walks)")
    print()
    print(f"  {'newly active':<26}{report.activated:>8,}")
    print(f"  {'deactivated (delisted)':<26}{report.deactivated:>8,}")
    print(f"  {'unchanged':<26}{report.unchanged:>8,}")
    print()
    print(f"  {'calls used':<26}{report.calls_used:>8,}")
    print(f"  {'bytes used':<26}{report.bytes_used:>8,}")
    if report.tickers:
        print(f"\n  sample: {', '.join(report.tickers[:15])}")

    if report.warning:
        print(f"\n  [WARNING] {report.warning}")
    return 0


async def show(limit: int) -> int:
    from sqlalchemy import func, select

    from app.core.database import async_session_maker
    from app.models.universe import Universe
    from app.models.universe_run import UniverseRun

    async with async_session_maker() as db:
        active = await db.scalar(
            select(func.count()).select_from(Universe).where(Universe.is_active.is_(True))
        )
        total = await db.scalar(select(func.count()).select_from(Universe))
        runs = (await db.execute(
            select(UniverseRun).order_by(UniverseRun.started_at.desc()).limit(limit)
        )).scalars().all()
        sample = (await db.execute(
            select(Universe.ticker).where(Universe.is_active.is_(True))
            .order_by(Universe.ticker).limit(15)
        )).scalars().all()

    print(f"\n  universe rows: {total:,}   active: {active:,}")
    if sample:
        print(f"  sample: {', '.join(sample)}")
    print(f"\n  {'started':<20}{'status':<11}{'size':>8}{'calls':>7}{'bytes':>12}  warning")
    for r in runs:
        print(f"  {r.started_at:%Y-%m-%d %H:%M}    {r.status:<11}"
              f"{(r.universe_size or 0):>8,}{r.calls_used:>7,}{r.bytes_used:>12,}  "
              f"{(r.warning or '')[:44]}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the Stage-1 universe.")
    parser.add_argument("--dry-run", action="store_true",
                        help="Fetch and report, write nothing (same API cost)")
    parser.add_argument("--show", action="store_true",
                        help="Read back the current universe and recent builds (0 calls)")
    parser.add_argument("--limit", type=int, default=10, help="Runs to show with --show")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)

    raise SystemExit(run_cli(show(args.limit) if args.show else build(args.dry_run)))
