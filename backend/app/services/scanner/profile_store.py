"""Reading `premarket_volume_profile` for the live scan.

The profile is RVOL's denominator: for each 5-minute bucket from 04:00 ET, the average
cumulative volume a ticker had reached by that clock time across the last ~20 sessions.
Phase 4B builds it; this loads it.

`sessions_sampled` travels with the buckets rather than being discarded, because RVOL will
happily divide by a 3-session average and produce a confident-looking number. Carrying the
count is what lets `NormalizedRvolWithFallback` refuse a thin profile and say so on the
alert instead.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.premarket_volume_profile import PremarketVolumeProfile


@dataclass(frozen=True)
class VolumeProfile:
    """One ticker's pre-market volume curve."""

    ticker: str
    # bucket_minute (minutes since 04:00 ET) -> average cumulative volume
    buckets: dict[int, float] = field(default_factory=dict)
    sessions_sampled: int = 0

    def __bool__(self) -> bool:
        return bool(self.buckets)


async def load_profiles(
    session: AsyncSession, tickers: list[str]
) -> dict[str, VolumeProfile]:
    """Load profiles for the given tickers in one query.

    One query rather than one per ticker: Stage 1 hands over ~694 candidates on a live
    pass, and 694 round-trips inside a 5-minute cadence is a self-inflicted wound.

    Tickers with no profile are simply absent — the caller degrades to simple RVOL and
    flags it, which is a better outcome than dropping a candidate that has just entered
    the universe and whose profile the next nightly build will create.
    """
    if not tickers:
        return {}

    rows = (await session.execute(
        select(PremarketVolumeProfile)
        .where(PremarketVolumeProfile.ticker.in_([t.upper() for t in tickers]))
        .order_by(PremarketVolumeProfile.ticker, PremarketVolumeProfile.bucket_minute)
    )).scalars().all()

    buckets: dict[str, dict[int, float]] = {}
    sessions: dict[str, int] = {}
    for row in rows:
        buckets.setdefault(row.ticker, {})[row.bucket_minute] = row.avg_cumulative_volume
        # Every row of a profile carries the same count; max() is defensive against a
        # partially-rewritten profile rather than meaningful.
        sessions[row.ticker] = max(sessions.get(row.ticker, 0), row.sessions_sampled)

    return {
        ticker: VolumeProfile(
            ticker=ticker, buckets=values, sessions_sampled=sessions.get(ticker, 0)
        )
        for ticker, values in buckets.items()
    }
