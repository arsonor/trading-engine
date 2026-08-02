"""Refresh `reference_data` from FMP end-of-day history.

Two calls per ticker (eod/full + shares-float). Budget-aware, idempotent and resumable:
re-running the same day costs ~0 calls, and an exhausted budget stops cleanly with
everything already written left intact.

    uv run python scripts/refresh_reference_data.py --tickers AAPL,MSFT --dry-run
    uv run python scripts/refresh_reference_data.py --limit 10
    uv run python scripts/refresh_reference_data.py --force --tickers AAPL
    uv run python scripts/refresh_reference_data.py --fixture      # no API calls
"""

import argparse
import time

# Import first: puts the backend directory on sys.path for the `app.*` imports below.
from _bootstrap import configure_logging, run_cli

from app.services.fmp.client import FmpClient
from app.services.fmp.fixtures import FixtureFmpClient
from app.services.reference.pipeline import (
    CALLS_PER_TICKER,
    STATUS_FAILED,
    STATUS_REFRESHED,
    STATUS_SKIPPED,
    STATUS_UNAVAILABLE,
    STATUS_WOULD_REFRESH,
    ReferenceRefresher,
    RefreshReport,
)


def _print_report(report: RefreshReport, elapsed: float, dry_run: bool, budget_line: str) -> None:
    print()
    print("Reference-data refresh" + (" (DRY RUN — no calls, no writes)" if dry_run else ""))
    print("=" * 72)
    for result in report.results:
        print(
            f"  {result.ticker:<8} {result.status:<14} "
            f"calls={result.calls_used}  {result.duration_s:5.2f}s  {result.detail}"
        )

    counts = report.by_status()
    print()
    print(f"  Tickers processed : {len(report.results)}")
    for status in (
        STATUS_REFRESHED,
        STATUS_WOULD_REFRESH,
        STATUS_SKIPPED,
        STATUS_UNAVAILABLE,
        STATUS_FAILED,
    ):
        if counts.get(status):
            print(f"    {status:<16}: {counts[status]}")
    print(f"  FMP calls used    : {report.calls_used}")
    print(f"  Wall time         : {elapsed:.1f}s")
    print(f"  {budget_line}")

    if report.stopped_early:
        print()
        print(f"  STOPPED EARLY: {report.stop_reason}")
        print("  Progress so far is committed; re-run to continue where this left off.")


async def main(args: argparse.Namespace) -> int:
    client = FixtureFmpClient() if args.fixture else FmpClient()
    refresher = ReferenceRefresher(client, force=args.force, dry_run=args.dry_run)

    try:
        if args.tickers:
            tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        else:
            tickers = await refresher.active_tickers(limit=args.limit)
            if not tickers:
                print(
                    "No eligible tickers in `universe`. "
                    "Run `uv run python scripts/probe_fmp_symbols.py` first."
                )
                return 1

        if args.limit and args.tickers:
            tickers = tickers[: args.limit]

        if not args.dry_run and client.budget.is_enabled:
            needed = len(tickers) * CALLS_PER_TICKER
            remaining = await client.budget.remaining_today()
            print(
                f"Refreshing {len(tickers)} ticker(s); up to {needed} call(s) needed, "
                f"{remaining} remaining in today's budget."
            )

        started = time.monotonic()
        report = await refresher.run(tickers)
        elapsed = time.monotonic() - started

        if client.budget.is_enabled:
            used = await client.budget.calls_used_today()
            budget_line = f"Budget today      : {used}/{client.budget.ceiling}"
        else:
            budget_line = "Budget today      : n/a (fixture replay makes no API calls)"

        _print_report(report, elapsed, args.dry_run, budget_line)
        return 2 if report.count(STATUS_FAILED) else 0
    finally:
        await client.aclose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Refresh reference data from FMP EOD history.")
    parser.add_argument("--tickers", help="Comma-separated tickers (default: active universe)")
    parser.add_argument("--limit", type=int, help="Process at most N tickers")
    parser.add_argument(
        "--force", action="store_true", help="Refresh even if already refreshed today"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Report what would happen; make no calls or writes"
    )
    parser.add_argument(
        "--fixture", action="store_true", help="Replay recorded responses instead of calling FMP"
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    raise SystemExit(run_cli(main(args)))
