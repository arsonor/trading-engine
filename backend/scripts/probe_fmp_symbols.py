"""Discover which symbols this FMP key can actually serve.

The free tier serves a sample of large caps that FMP does not publish, so the V1 universe
is measured rather than assumed. The accessible set this reports IS the V1 universe.

    uv run python scripts/probe_fmp_symbols.py
    uv run python scripts/probe_fmp_symbols.py --symbols AAPL,MSFT,SNDL
    uv run python scripts/probe_fmp_symbols.py --show-universe   # no API calls

Cost: one FMP call per 25 candidates (~4 calls for the default list).
"""

import argparse

# Import first: puts the backend directory on sys.path for the `app.*` imports below.
from _bootstrap import configure_logging, run_cli

from app.services.fmp.client import FmpClient
from app.services.fmp.errors import BudgetExhausted, FmpError
from app.services.reference.probe import CONTROL_GROUP, DEFAULT_CANDIDATES, SymbolProber


def _print_report(report, sample: int) -> None:
    print()
    print("FMP free-tier symbol probe")
    print("=" * 62)
    print(f"  Candidates tested : {len(report.accessible) + len(report.inaccessible)}")
    print(f"  Accessible        : {len(report.accessible)}")
    print(f"  Not available     : {len(report.inaccessible)}")
    print(f"  Probe method      : {report.mode}")
    print(f"  FMP calls used    : {report.calls_used}")

    for note in report.notes:
        print(f"  Note              : {note}")

    if report.accessible:
        shown = report.accessible[:sample]
        print(f"  Sample            : {', '.join(shown)}" + (" ..." if len(shown) < len(report.accessible) else ""))

    control_hits = report.control_accessible
    print()
    if control_hits:
        print(
            "  Control group: "
            f"{', '.join(control_hits)} answered unexpectedly — the free-tier restriction "
            "is not what we assumed. Re-check the universe assumptions before Phase 2."
        )
    else:
        blocked = sorted(CONTROL_GROUP & set(report.inaccessible))
        print(
            f"  Control group: all {len(blocked)} small caps correctly blocked "
            f"({', '.join(blocked)}) — the probe can detect a negative."
        )

    if report.stopped_early:
        print()
        print(f"  STOPPED EARLY: {report.stop_reason}")
        print("  The persisted universe is partial; re-run after the budget resets.")

    print()
    print(f"  Universe persisted to `universe` table: {report.universe_size} accessible ticker(s).")


async def main(args: argparse.Namespace) -> int:
    prober = SymbolProber(FmpClient())

    if args.show_universe:
        universe = await prober.accessible_universe()
        print(f"Known accessible universe ({len(universe)} tickers):")
        print("  " + ", ".join(universe) if universe else "  (empty — run the probe first)")
        return 0

    candidates = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else DEFAULT_CANDIDATES
    )
    if args.limit:
        candidates = candidates[: args.limit]

    print(
        f"Probing {len(candidates)} candidate(s). Cost: 1 call per 25 on plans with "
        f"batch-quote, otherwise 1 call per symbol (the free tier restricts batch-quote)."
    )

    try:
        report = await prober.probe(candidates)
    except BudgetExhausted as exc:
        print(f"Budget exhausted before probing: {exc}")
        return 2
    except FmpError as exc:
        print(f"Probe failed: {exc}")
        return 1

    _print_report(report, args.sample)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Probe FMP for accessible symbols.")
    parser.add_argument("--symbols", help="Comma-separated candidates (default: built-in list)")
    parser.add_argument("--sample", type=int, default=15, help="How many accessible symbols to show")
    parser.add_argument("--limit", type=int, help="Probe at most N candidates (caps the cost)")
    parser.add_argument(
        "--show-universe",
        action="store_true",
        help="Print the persisted accessible universe without calling FMP",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    raise SystemExit(run_cli(main(args)))
