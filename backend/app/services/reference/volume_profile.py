"""Build `premarket_volume_profile` — the denominator for time-of-day-normalized RVOL.

## What a profile is

For each ticker and each 5-minute bucket from 04:00 ET, the **average cumulative** volume
that ticker had reached by that clock time across the last ~20 sessions. RVOL then divides
today's cumulative volume at the same bucket by this number, which is what makes "twice its
usual volume for 7am" expressible at all. Dividing by a full-day average instead — the V1
`simple` mode — compares a 3-hour pre-market figure against a 6.5-hour denominator and is
wrong by a factor that varies with the time of day.

## Three measured constraints from Phase 4A shape this

1. **Volume is per-bar, not cumulative**, so the running sum is computed here rather than
   read from a field. `app/services/bars.cumulative_by_bucket` owns that.
2. **Long ranges are silently truncated** to their most recent portion by a per-request row
   cap, so history is fetched a week at a time. Asking for 20 sessions in one call returns
   about 8 and gives no indication that anything was dropped.
3. **Bars are revised upward for ~7 minutes after they close.** Historical sessions are
   long settled, so this mostly matters for today — but the *same* `settled_bars()` helper
   is used here as on the live path, because the two numbers are divided by each other and
   a mismatch biases RVOL low by construction. See `app/services/bars.py`.

## Thin history is flagged, never averaged silently

A profile built from 3 sessions is not a worse version of a 20-session profile; it is a
different, much noisier quantity that RVOL will nonetheless divide by with full confidence.
`sessions_sampled` is stored on every row, and profiles below `profile_sessions_min` are
reported as thin so the caller can refuse to trust them.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.premarket_volume_profile import PremarketVolumeProfile
from app.services.bars import Bar, cumulative_by_bucket, market_tz, settled_bars
from app.services.fmp.client import FmpClient
from app.services.fmp.errors import BudgetExhausted, FmpError

logger = logging.getLogger(__name__)


@dataclass
class TickerProfileResult:
    ticker: str
    status: str
    sessions: int = 0
    buckets: int = 0
    calls_used: int = 0
    detail: str = ""


@dataclass
class ProfileReport:
    results: list[TickerProfileResult] = field(default_factory=list)
    stopped_early: bool = False
    stop_reason: str = ""

    @property
    def calls_used(self) -> int:
        return sum(r.calls_used for r in self.results)

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    @property
    def thin(self) -> list[TickerProfileResult]:
        return [r for r in self.results if r.status == STATUS_THIN]


STATUS_BUILT = "built"
STATUS_THIN = "thin"
STATUS_NO_DATA = "no_data"
STATUS_SKIPPED = "skipped"
STATUS_FAILED = "failed"
STATUS_STOPPED = "stopped"


def _to_bars(rows, tz) -> list[Bar]:
    """FMP intraday timestamps are naive market-local; attach the market timezone."""
    return [
        Bar(start=r.date.replace(tzinfo=tz), volume=r.volume, close=r.close)
        for r in rows
    ]


class VolumeProfileBuilder:
    """Populates `premarket_volume_profile` from extended-hours intraday history."""

    def __init__(
        self,
        client: FmpClient,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        force: bool = False,
    ) -> None:
        if session_factory is None:
            from app.core.database import async_session_maker

            session_factory = async_session_maker
        self._client = client
        self._session_factory = session_factory
        self._force = force
        self._settings = get_settings()
        self._tz = market_tz()

    # ------------------------------------------------------------------ selection

    async def stage1_tickers(self, limit: int | None = None) -> list[str]:
        """Tickers that currently clear the PRODUCTION Stage-1 filters.

        Profiles are built for this set, not the whole maintained universe: at ~4 calls per
        ticker, profiling 3,948 names would cost ~16,000 calls a night to produce
        denominators for tickers the scanner will never reach Stage 2 with.
        """
        from app.models.reference_data import ReferenceData
        from app.models.universe import Universe

        s = self._settings
        async with self._session_factory() as session:
            stmt = (
                select(ReferenceData.ticker)
                .join(Universe, Universe.ticker == ReferenceData.ticker)
                .where(
                    Universe.is_active.is_(True),
                    ReferenceData.static_float.isnot(None),
                    ReferenceData.static_float < s.scan_float_max,
                    ReferenceData.volume_avg_20d.isnot(None),
                    ReferenceData.volume_avg_20d > s.scan_avg_volume_min,
                )
                .order_by(ReferenceData.ticker)
            )
            if limit:
                stmt = stmt.limit(limit)
            return list((await session.execute(stmt)).scalars().all())

    # ------------------------------------------------------------------ fetching

    async def fetch_sessions(
        self, ticker: str, target_sessions: int, upto: date
    ) -> tuple[dict[date, list[Bar]], int]:
        """Fetch extended-hours bars a week at a time until enough sessions are collected.

        Returns (sessions, calls). Paginating is not an optimisation — a single wide
        request comes back truncated to its most recent portion with no error, so asking
        for 20 sessions at once silently yields about 8.
        """
        per_request = self._settings.profile_fetch_days_per_request
        sessions: dict[date, list[Bar]] = defaultdict(list)
        calls = 0
        window_end = upto
        # Enough windows to reach the target even across holidays, with a hard stop so a
        # ticker that simply has no history cannot spin.
        max_windows = max(4, (target_sessions // 3) + 4)

        for _ in range(max_windows):
            if len({d for d in sessions if sessions[d]}) >= target_sessions:
                break
            window_start = window_end - timedelta(days=per_request - 1)
            rows = await self._client.get_intraday_bars(
                ticker, interval="5min", start=window_start, end=window_end, extended=True
            )
            calls += 1
            for bar in _to_bars(rows, self._tz):
                sessions[bar.start.date()].append(bar)
            window_end = window_start - timedelta(days=1)

        return {d: b for d, b in sessions.items() if b}, calls

    # ------------------------------------------------------------------ computation

    def average_profile(
        self, sessions: dict[date, list[Bar]], target_sessions: int
    ) -> tuple[dict[int, float], int]:
        """Average the cumulative curve across sessions, newest `target_sessions` first.

        Each session contributes its own running sum per bucket. A bucket is averaged over
        the sessions that actually reached it — a ticker that did not trade before 06:00 on
        some days should not have those days counted as zeros at 04:00, which would drag
        the denominator down and inflate RVOL.
        """
        chosen = sorted(sessions, reverse=True)[:target_sessions]
        totals: dict[int, float] = defaultdict(float)
        counts: dict[int, int] = defaultdict(int)

        for day in chosen:
            # Historical sessions are fully settled; `now=None` says so explicitly rather
            # than relying on the current clock being far enough past them.
            bars = settled_bars(sessions[day], now=None)
            for bucket, cumulative in cumulative_by_bucket(bars).items():
                totals[bucket] += cumulative
                counts[bucket] += 1

        profile = {b: totals[b] / counts[b] for b in totals if counts[b]}
        return profile, len(chosen)

    # ------------------------------------------------------------------ persistence

    async def _store(self, ticker: str, profile: dict[int, float], sessions: int) -> int:
        """Replace this ticker's profile, safely against a concurrent builder.

        **Upsert, then delete what is no longer part of the profile** — not delete-then-
        insert. The obvious ordering loses a race: two overlapping builds can interleave as
        delete(A), insert(B), insert(A) and the second insert dies on the unique
        constraint, leaving A's profile half-written. That is not hypothetical; it happened
        during this phase's own build when two runs overlapped, and on Render a nightly job
        that runs long enough to meet the next one would reproduce it.

        `ON CONFLICT DO UPDATE` makes each bucket write idempotent, so concurrent builders
        converge instead of colliding. The trailing delete removes buckets from a previous,
        longer history that the new profile no longer covers — without it a ticker that
        stopped trading early would keep stale late-session buckets forever, and RVOL would
        divide by a denominator from a market that no longer exists.
        """
        now = datetime.utcnow()
        rows = [
            {
                "ticker": ticker,
                "bucket_minute": bucket,
                "avg_cumulative_volume": value,
                "sessions_sampled": sessions,
                "computed_at": now,
            }
            for bucket, value in sorted(profile.items())
        ]
        async with self._session_factory() as session:
            if rows:
                stmt = pg_insert(PremarketVolumeProfile).values(rows)
                await session.execute(
                    stmt.on_conflict_do_update(
                        constraint="uq_premarket_profile_ticker_bucket",
                        set_={
                            "avg_cumulative_volume": stmt.excluded.avg_cumulative_volume,
                            "sessions_sampled": stmt.excluded.sessions_sampled,
                            "computed_at": stmt.excluded.computed_at,
                        },
                    )
                )
            await session.execute(
                delete(PremarketVolumeProfile).where(
                    PremarketVolumeProfile.ticker == ticker,
                    PremarketVolumeProfile.bucket_minute.notin_(list(profile) or [-1]),
                )
            )
            await session.commit()
        return len(profile)

    async def _is_fresh_today(self, ticker: str) -> bool:
        async with self._session_factory() as session:
            computed = await session.scalar(
                select(PremarketVolumeProfile.computed_at)
                .where(PremarketVolumeProfile.ticker == ticker)
                .limit(1)
            )
        return computed is not None and computed.date() == datetime.utcnow().date()

    # ------------------------------------------------------------------ entry points

    async def build_ticker(self, ticker: str, upto: date) -> TickerProfileResult:
        ticker = ticker.strip().upper()
        target = self._settings.profile_sessions_target

        if not self._force and await self._is_fresh_today(ticker):
            return TickerProfileResult(ticker, STATUS_SKIPPED, detail="already built today")

        try:
            sessions, calls = await self.fetch_sessions(ticker, target, upto)
        except BudgetExhausted as exc:
            return TickerProfileResult(ticker, STATUS_STOPPED, detail=str(exc))
        except FmpError as exc:
            return TickerProfileResult(ticker, STATUS_FAILED, detail=str(exc))

        if not sessions:
            return TickerProfileResult(
                ticker, STATUS_NO_DATA, calls_used=calls,
                detail="no extended-hours bars returned",
            )

        profile, used_sessions = self.average_profile(sessions, target)
        if not profile:
            return TickerProfileResult(
                ticker, STATUS_NO_DATA, calls_used=calls, sessions=used_sessions,
                detail="bars returned but none inside 04:00-09:30 ET",
            )

        buckets = await self._store(ticker, profile, used_sessions)
        thin = used_sessions < self._settings.profile_sessions_min
        return TickerProfileResult(
            ticker,
            STATUS_THIN if thin else STATUS_BUILT,
            sessions=used_sessions,
            buckets=buckets,
            calls_used=calls,
            detail=(
                f"{used_sessions} session(s) — BELOW the {self._settings.profile_sessions_min}"
                f"-session minimum, treat RVOL from this profile as unreliable"
                if thin else f"{used_sessions} session(s), {buckets} buckets"
            ),
        )

    async def run(self, tickers: list[str], upto: date | None = None) -> ProfileReport:
        report = ProfileReport()
        upto = upto or datetime.now(self._tz).date()

        for ticker in tickers:
            result = await self.build_ticker(ticker, upto)
            report.results.append(result)
            logger.info(
                "volume_profile ticker=%s status=%s sessions=%s buckets=%s calls=%s",
                result.ticker, result.status, result.sessions, result.buckets,
                result.calls_used,
            )
            if result.status == STATUS_STOPPED:
                report.stopped_early = True
                report.stop_reason = result.detail
                break

        return report
