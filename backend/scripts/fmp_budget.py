"""Show today's FMP API budget usage.

    uv run python scripts/fmp_budget.py
    uv run python scripts/fmp_budget.py --history 7
"""

import argparse
import asyncio

# Import first: puts the backend directory on sys.path for the `app.*` imports below.
from _bootstrap import configure_logging

from app.config import get_settings
from app.services.fmp.budget import DailyBudgetGuard, next_utc_midnight, utc_today


async def main(history: int) -> int:
    settings = get_settings()
    guard = DailyBudgetGuard()

    used = await guard.calls_used_today()
    remaining = await guard.remaining_today()
    pct = (used / guard.ceiling * 100) if guard.ceiling else 0.0

    print("FMP daily API budget")
    print("=" * 52)
    print(f"  UTC date        : {utc_today()}")
    print(f"  Calls used      : {used}")
    print(f"  Local ceiling   : {guard.ceiling}   (FMP_DAILY_BUDGET)")
    print(f"  Remaining       : {remaining}  ({pct:.1f}% of ceiling used)")
    print(f"  Resets at       : {next_utc_midnight().isoformat()}")
    print(f"  Base URL        : {settings.fmp_base_url}")
    print(f"  API key         : {'set' if settings.fmp_api_key else 'MISSING'}")

    if history > 0:
        rows = await guard.history(limit=history)
        if rows:
            print()
            print(f"Last {len(rows)} day(s):")
            for row in rows:
                print(f"  {row.budget_date}  {row.calls_used:>4} calls  ({row.provider})")

    if remaining == 0:
        print()
        print("  Budget exhausted — FMP calls will be refused until reset.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Show FMP daily API budget usage.")
    parser.add_argument("--history", type=int, default=7, help="Show the last N days (0 to hide)")
    args = parser.parse_args()
    configure_logging()
    raise SystemExit(asyncio.run(main(args.history)))
