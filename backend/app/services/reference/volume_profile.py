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
from app.models.premarket_session_volume import PremarketSessionVolume
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

    async def fetch_missing_sessions(
        self,
        ticker: str,
        target_sessions: int,
        upto: date,
        stored: dict[date, dict[int, float]],
    ) -> tuple[dict[date, list[Bar]], int]:
        """Fetch forward from the newest stored session to `upto`, and nothing else.

        On an ordinary night that is one trading day: **one request**, against the four a
        20-session rebuild takes. With nothing stored it degrades to the original full
        fetch, so the first night after deployment and `--rebuild` behave as before.

        ## Why it does not also fetch backwards to fill a short history

        Tempting, and wrong. A stored history shorter than `target_sessions` has two
        possible causes and **stored data cannot tell them apart**: the ticker genuinely
        has no more history (a recent listing), or a build was interrupted. The first is
        overwhelmingly the common case, because the initial build already paginates back up
        to ~70 calendar days before giving up.

        Probing backwards each night therefore spends real calls re-discovering that a
        young ticker is still young — measured at 5 wasted requests per ticker per night in
        the first draft of this method, every night, forever. Knowing when to stop would
        need a "probed back to" marker, which is state to store, migrate and keep honest.

        `--rebuild` is the repair path instead. It is also the answer when
        `profile_sessions_target` is raised: every profile is short by definition after
        that change, and a deliberate operator action is the right way to refill them.
        """
        if not stored:
            return await self.fetch_sessions(ticker, target_sessions, upto)

        per_request = self._settings.profile_fetch_days_per_request
        newest = max(stored)
        sessions: dict[date, list[Bar]] = defaultdict(list)
        calls = 0

        # Nothing to do when the newest stored session is already `upto` — the common case
        # for a same-day re-run that got past the freshness check.
        window_end = upto
        while window_end > newest:
            window_start = max(
                newest + timedelta(days=1), window_end - timedelta(days=per_request - 1)
            )
            rows = await self._client.get_intraday_bars(
                ticker, interval="5min", start=window_start, end=window_end, extended=True
            )
            calls += 1
            for bar in _to_bars(rows, self._tz):
                # Bars for sessions already stored are ignored rather than re-averaged:
                # a settled session does not change, and re-reducing it would only add a
                # way for the stored and fetched forms to disagree.
                if bar.start.date() > newest:
                    sessions[bar.start.date()].append(bar)
            window_end = window_start - timedelta(days=1)

        return {d: b for d, b in sessions.items() if b}, calls

    # ------------------------------------------------------------------ computation

    def session_curves(self, sessions: dict[date, list[Bar]]) -> dict[date, dict[int, float]]:
        """Reduce each session's bars to its cumulative curve.

        Split out from `average_profile` so a curve can come either from bars just fetched
        or from `premarket_session_volume` — the incremental path averages both together,
        and they must be reduced identically or a stored session would not equal the same
        session re-fetched.
        """
        curves: dict[date, dict[int, float]] = {}
        for day, bars in sessions.items():
            # Historical sessions are fully settled; `now=None` says so explicitly rather
            # than relying on the current clock being far enough past them.
            #
            # An EMPTY curve is kept, not dropped. A session that traded only in regular
            # hours still counts as a session that was fetched — it simply adds no buckets,
            # so it cannot dilute the average of the sessions that did trade pre-market.
            # Dropping it would understate `sessions_sampled`, and on the incremental path
            # it would also leave the forward cursor stuck: an unstored newest session gets
            # re-fetched every night forever.
            curves[day] = cumulative_by_bucket(settled_bars(bars, now=None))
        return curves

    def average_curves(
        self, curves: dict[date, dict[int, float]], target_sessions: int
    ) -> tuple[dict[int, float], int]:
        """Average cumulative curves, newest `target_sessions` first.

        A bucket is averaged over the sessions that actually reached it — a ticker that did
        not trade before 06:00 on some days should not have those days counted as zeros at
        04:00, which would drag the denominator down and inflate RVOL.

        That per-bucket count is also why the profile alone cannot be rolled forward: there
        is no single divisor to subtract a departing session from. See
        `app/models/premarket_session_volume.py`.
        """
        chosen = sorted(curves, reverse=True)[:target_sessions]
        totals: dict[int, float] = defaultdict(float)
        counts: dict[int, int] = defaultdict(int)

        for day in chosen:
            for bucket, cumulative in curves[day].items():
                totals[bucket] += cumulative
                counts[bucket] += 1

        profile = {b: totals[b] / counts[b] for b in totals if counts[b]}
        return profile, len(chosen)

    def average_profile(
        self, sessions: dict[date, list[Bar]], target_sessions: int
    ) -> tuple[dict[int, float], int]:
        """Average the cumulative curve across sessions, newest `target_sessions` first."""
        return self.average_curves(self.session_curves(sessions), target_sessions)

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

    async def load_session_curves(self, ticker: str) -> dict[date, dict[int, float]]:
        """Curves already stored for this ticker, newest-first ordering not guaranteed."""
        async with self._session_factory() as session:
            rows = await session.scalars(
                select(PremarketSessionVolume).where(
                    PremarketSessionVolume.ticker == ticker
                )
            )
            return {row.session_date: row.bucket_map() for row in rows}

    async def _store_session_curves(
        self, ticker: str, curves: dict[date, dict[int, float]], bar_counts: dict[date, int]
    ) -> None:
        """Upsert one row per session.

        `ON CONFLICT DO UPDATE` for the same reason the profile write uses it: two nightly
        runs overlapping on Render must converge rather than collide, and that has already
        happened once in this phase.
        """
        if not curves:
            return
        now = datetime.utcnow()
        rows = [
            {
                "ticker": ticker,
                "session_date": day,
                # JSON object keys are strings on the way back out; `bucket_map()` is the
                # reader that undoes this.
                "buckets": {str(bucket): value for bucket, value in curve.items()},
                "bars_used": bar_counts.get(day, 0),
                "computed_at": now,
            }
            for day, curve in sorted(curves.items())
        ]
        async with self._session_factory() as session:
            stmt = pg_insert(PremarketSessionVolume).values(rows)
            await session.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_premarket_session_volume_ticker_date",
                    set_={
                        "buckets": stmt.excluded.buckets,
                        "bars_used": stmt.excluded.bars_used,
                        "computed_at": stmt.excluded.computed_at,
                    },
                )
            )
            await session.commit()

    async def _prune_sessions(self, ticker: str, keep: list[date]) -> int:
        """Drop sessions that have fallen outside the rolling window.

        Without this the table grows without bound and the "drop the oldest" half of the
        incremental rebuild never happens — the profile would stay correct, since averaging
        takes the newest N, but the storage claim would not.
        """
        async with self._session_factory() as session:
            result = await session.execute(
                delete(PremarketSessionVolume).where(
                    PremarketSessionVolume.ticker == ticker,
                    PremarketSessionVolume.session_date.notin_(keep or [date.min]),
                )
            )
            await session.commit()
            return result.rowcount or 0

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

        # Stored curves are the whole point of the incremental path: a fresh night should
        # cost the sessions it is MISSING, not all 20. `--rebuild` ignores them, which is
        # what makes it a real reconstruction rather than a no-op.
        stored = {} if self._force else await self.load_session_curves(ticker)

        try:
            fetched, calls = await self.fetch_missing_sessions(ticker, target, upto, stored)
        except BudgetExhausted as exc:
            return TickerProfileResult(ticker, STATUS_STOPPED, detail=str(exc))
        except FmpError as exc:
            return TickerProfileResult(ticker, STATUS_FAILED, detail=str(exc))

        fresh_curves = self.session_curves(fetched)
        if fresh_curves:
            await self._store_session_curves(
                ticker, fresh_curves, {d: len(b) for d, b in fetched.items()}
            )

        curves = {**stored, **fresh_curves}
        if not curves:
            return TickerProfileResult(
                ticker, STATUS_NO_DATA, calls_used=calls,
                detail="no extended-hours bars returned",
            )

        profile, used_sessions = self.average_curves(curves, target)
        if not profile:
            return TickerProfileResult(
                ticker, STATUS_NO_DATA, calls_used=calls, sessions=used_sessions,
                detail="bars returned but none inside 04:00-09:30 ET",
            )

        # The other half of "add the newest, drop the oldest".
        await self._prune_sessions(ticker, sorted(curves, reverse=True)[:target])

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
