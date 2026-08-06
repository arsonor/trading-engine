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


async def _record_premium(store: FixtureStore, symbol: str) -> None:
    """Record the Premium shapes Phase 4B depends on, so CI can replay them offline.

    The important one is the **multi-session** `extended=true` window: the volume-profile
    builder pages through history a week at a time, and a single-day fixture cannot
    exercise the session-grouping or the averaging across sessions at all.

    Collection endpoints are sliced. `shares-float-all` and `company-screener` are ~0.7 MB
    per page and the value of a fixture is the shape of a row, not five thousand of them;
    the slice is recorded in the note so a truncated page is never mistaken for a full one.
    """
    from datetime import date, timedelta

    from app.services.fmp.client import (
        EP_HISTORICAL_CHART,
        EP_SCREENER,
        EP_SHARES_FLOAT_ALL,
        FmpClient,
    )

    end = date.today()
    start = end - timedelta(days=13)  # two weeks: several sessions, still one request
    client = FmpClient()
    print("\nPremium fixtures (Phase 4B):")
    try:
        targets = [
            (f"{EP_HISTORICAL_CHART}/5min",
             {"symbol": symbol, "from": start.isoformat(), "to": end.isoformat(),
              "extended": "true"},
             None, f"extended=true, {start}..{end} — multi-session window for profiles"),
            (EP_SHARES_FLOAT_ALL, {"limit": 5000, "page": 0}, 25, "bulk float"),
            (EP_SCREENER,
             {"priceMoreThan": 1.6, "isEtf": "false", "isFund": "false",
              "isActivelyTrading": "true", "country": "US", "limit": 10000},
             25, "universe pre-filter"),
        ]
        for endpoint, params, slice_n, note in targets:
            raw = await client._raw_get(endpoint, params)
            payload = raw.payload
            full = len(payload) if isinstance(payload, list) else None
            if slice_n and isinstance(payload, list):
                payload = payload[:slice_n]
                note = f"{note} (first {slice_n} of {full} rows)"
            elif isinstance(payload, list):
                note = f"{note} ({full} bars)"
            path = store.save(endpoint, params, raw.status, payload, note=note)
            print(f"  [ok]   {path.name[:66]}")
    except FmpError as exc:
        print(f"  [err]  premium fixtures: {exc}")
    finally:
        await client.aclose()


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

    if not args.skip_premium:
        await _record_premium(store, args.premium_symbol)

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
    parser.add_argument(
        "--skip-premium", action="store_true",
        help="Skip the Phase 4B Premium fixtures (extended bars, bulk float, screener)",
    )
    parser.add_argument(
        "--premium-symbol", default="FFAI",
        help="Low-float symbol for the multi-session extended=true fixture",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    configure_logging(args.verbose)
    raise SystemExit(run_cli(main(args)))
