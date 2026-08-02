"""Record real FMP responses to `tests/fixtures/fmp/` for offline replay.

This is the ONLY code path in the project that hits live FMP from a test-support context,
and it is still budget-guarded — recording costs real quota. Run it manually, once, and
commit the result. CI replays; CI never calls.

    uv run python scripts/record_fmp_fixtures.py --dry-run
    uv run python scripts/record_fmp_fixtures.py
    uv run python scripts/record_fmp_fixtures.py --symbols AAPL,MSFT

Default cost: 5 accessible symbols x 2 calls + 1 unavailable symbol x 1 call = 11 calls.
"""

import argparse

# Import first: puts the backend directory on sys.path for the `app.*` imports below.
from _bootstrap import configure_logging, run_cli

from app.services.fmp.client import EP_EOD_FULL, EP_SHARES_FLOAT
from app.services.fmp.errors import BudgetExhausted, FmpError, SymbolNotAvailable
from app.services.fmp.fixtures import FixtureStore, RecordingFmpClient

# Five large caps that the free tier is expected to serve.
DEFAULT_SYMBOLS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD"]

# A symbol the free tier should refuse — the "not available" path needs a fixture too,
# because that branch runs constantly in production and must be tested.
DEFAULT_UNAVAILABLE = "SNDL"

# Hand-written degenerate cases. FMP cannot be asked to return garbage on demand, so the
# malformed and empty fixtures are synthesized rather than recorded.
SYNTHETIC_FIXTURES = [
    (
        EP_EOD_FULL,
        {"symbol": "__EMPTY__"},
        200,
        [],
        "Synthetic: endpoint returns 200 with an empty list (no data for symbol).",
    ),
    (
        EP_EOD_FULL,
        {"symbol": "__MALFORMED__"},
        200,
        [{"date": "2026-07-24", "open": 10.0, "high": "not-a-number"}],
        "Synthetic: row missing required fields with a non-numeric high.",
    ),
    (
        EP_SHARES_FLOAT,
        {"symbol": "__NOFLOAT__"},
        200,
        [{"symbol": "__NOFLOAT__", "date": "2026-07-24"}],
        "Synthetic: shares-float row with no float figures (null-tolerant path).",
    ),
]


async def main(args: argparse.Namespace) -> int:
    store = FixtureStore()
    symbols = (
        [s.strip().upper() for s in args.symbols.split(",") if s.strip()]
        if args.symbols
        else DEFAULT_SYMBOLS
    )
    planned = len(symbols) * 2 + 1

    print(f"Fixture directory : {store.root.resolve()}")
    print(f"Symbols           : {', '.join(symbols)}")
    print(f"Unavailable probe : {args.unavailable}")
    print(f"Planned API calls : {planned}")

    if args.dry_run:
        print("\nDRY RUN — nothing recorded.")
        for symbol in symbols:
            print(f"  would record {store.path_for(EP_EOD_FULL, {'symbol': symbol}).name}")
            print(f"  would record {store.path_for(EP_SHARES_FLOAT, {'symbol': symbol}).name}")
        for endpoint, params, _status, _payload, _note in SYNTHETIC_FIXTURES:
            print(f"  would write   {store.path_for(endpoint, params).name} (synthetic)")
        return 0

    client = RecordingFmpClient(store=store)
    recorded = 0
    try:
        for symbol in symbols:
            # Build the coroutine lazily — creating both up front would leave one
            # un-awaited whenever the first raises.
            for label, call in (
                ("eod", lambda s=symbol: client.get_eod_history(s)),
                ("float", lambda s=symbol: client.get_shares_float(s)),
            ):
                try:
                    await call()
                    recorded += 1
                    print(f"  [ok]   {symbol:<6} {label}")
                except BudgetExhausted as exc:
                    print(f"\nBudget exhausted: {exc}")
                    print(f"Recorded {recorded} fixture(s) before stopping.")
                    return 2
                except FmpError as exc:
                    # The response was still captured by the recorder before the error
                    # was raised — that failure shape is exactly what tests need.
                    print(f"  [err]  {symbol:<6} {label}: {exc}")

        try:
            await client.get_eod_history(args.unavailable)
            print(
                f"  [warn] {args.unavailable} was ACCESSIBLE — pick a different symbol "
                f"for the not-available fixture."
            )
        except SymbolNotAvailable as exc:
            print(f"  [ok]   {args.unavailable:<6} recorded as not-available: {exc}")
        except BudgetExhausted as exc:
            print(f"\nBudget exhausted: {exc}")
            return 2
        except FmpError as exc:
            print(f"  [err]  {args.unavailable:<6} {exc}")
    finally:
        await client.aclose()

    for endpoint, params, status, payload, note in SYNTHETIC_FIXTURES:
        path = store.save(endpoint, params, status, payload, note=note)
        print(f"  [ok]   synthetic {path.name}")

    print()
    print(f"Fixtures on disk  : {len(store.keys())}")
    print(f"Calls used today  : {await client.budget.calls_used_today()}/{client.budget.ceiling}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Record FMP fixtures for offline tests.")
    parser.add_argument("--symbols", help=f"Comma-separated (default: {','.join(DEFAULT_SYMBOLS)})")
    parser.add_argument(
        "--unavailable",
        default=DEFAULT_UNAVAILABLE,
        help="A symbol expected to be refused by the free tier",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show the plan without calling FMP")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    raise SystemExit(run_cli(main(args)))
