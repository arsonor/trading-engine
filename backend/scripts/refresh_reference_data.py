"""Refresh `reference_data` from FMP end-of-day history.

**One call per ticker at scale.** Float used to cost a second call per ticker; since
Phase 4B it comes from `shares-float-all`, which returns the whole market in ~8 calls
regardless of universe size. On a 3,948-ticker universe that is 3,956 calls instead of
7,896. Pass `--no-bulk-float` to restore the per-ticker path.

Budget- and bandwidth-aware, idempotent and resumable: re-running the same day costs ~0
calls, and an exhausted budget stops cleanly with everything already written left intact.

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


async def _bulk_float_lookup(client) -> dict[str, object] | None:
    """Fetch float for the whole market once, instead of once per ticker.

    ~8 calls total regardless of universe size, which is what makes a 3,948-ticker nightly
    refresh affordable: 3,956 calls instead of 7,896. Returns None on failure so the run
    falls back to the per-ticker path rather than refreshing everything with no float —
    a reference_data row without `static_float` cannot pass Stage 1 at all.
    """
    page = -1
    try:
        rows: dict[str, object] = {}
        for page in range(12):
            page_rows = await client.get_shares_float_page(page=page)
            if not page_rows:
                break
            for row in page_rows:
                rows[row.symbol.upper()] = row
            if len(page_rows) < 5000:
                break
        print(f"  Bulk float: {len(rows):,} symbols in {page + 1} call(s)")
        return rows
    except Exception as exc:  # noqa: BLE001 - fall back, do not abort the refresh
        print(f"  Bulk float unavailable ({type(exc).__name__}: {exc}); "
              f"falling back to one shares-float call per ticker.")
        return None


async def main(args: argparse.Namespace) -> int:
    client = FixtureFmpClient() if args.fixture else FmpClient()

    # The fixture client replays single-symbol shapes; bulk float has no fixture path, so
    # replay keeps the original per-ticker behaviour.
    float_lookup = None
    if not args.fixture and not args.dry_run and not args.no_bulk_float:
        float_lookup = await _bulk_float_lookup(client)

    refresher = ReferenceRefresher(
        client, force=args.force, dry_run=args.dry_run, float_lookup=float_lookup
    )

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
            needed = len(tickers) * refresher.calls_per_ticker
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
            bw = await client.budget.bandwidth_status()
            warn = "  [WARNING: past the warn threshold]" if bw["over_warn_threshold"] else ""
            budget_line = (
                f"Budget today      : {used}/{client.budget.ceiling} calls\n"
                f"  Bandwidth (30d)   : {bw['bytes_30d'] / 1e9:.2f} GB of "
                f"{bw['allowance_bytes'] / 1e9:.0f} GB ({bw['pct_used']}%){warn}"
            )
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
    parser.add_argument(
        "--no-bulk-float", action="store_true",
        help="Fetch float per ticker instead of one bulk call (slower, more calls)",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    raise SystemExit(run_cli(main(args)))
