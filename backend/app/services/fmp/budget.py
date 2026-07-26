"""Daily FMP API budget guard.

Every FMP call goes through `DailyBudgetGuard.reserve()` *before* the HTTP request is
made. The counter is in Postgres, not memory, because cron jobs and the web service are
separate processes and the free tier's 250/day cap is shared between them.

Reservation is a single conditional UPDATE:

    UPDATE api_budget SET calls_used = calls_used + 1
    WHERE budget_date = :today AND calls_used < :ceiling
    RETURNING calls_used

If no row comes back, the ceiling is reached — atomic, with no read-then-write race
between concurrent workers. Each reservation commits in its own session so a job that
crashes later still leaves an accurate count behind; the budget must never be
over-reported as available.
"""

import logging
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.api_budget import ApiBudget
from app.services.fmp.errors import BudgetExhausted

logger = logging.getLogger(__name__)


def utc_today() -> date:
    """Today's date in UTC — FMP's quota resets at 00:00 UTC, not local midnight."""
    return datetime.now(timezone.utc).date()


def next_utc_midnight(now: datetime | None = None) -> datetime:
    """The next 00:00 UTC boundary, i.e. when the provider quota resets."""
    now = now or datetime.now(timezone.utc)
    return datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), tzinfo=timezone.utc)


class DailyBudgetGuard:
    """Enforces a hard per-UTC-day ceiling on outbound FMP calls."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        ceiling: int | None = None,
        provider: str = "fmp",
    ) -> None:
        settings = get_settings()
        if session_factory is None:
            # Imported lazily so tests can build a guard without touching the real engine.
            from app.core.database import async_session_maker

            session_factory = async_session_maker
        self._session_factory = session_factory
        self._ceiling = settings.fmp_daily_budget if ceiling is None else ceiling
        self._provider = provider

    @property
    def ceiling(self) -> int:
        return self._ceiling

    @property
    def is_enabled(self) -> bool:
        """False only for guards fronting a path that makes no real API calls."""
        return True

    async def _ensure_row(self, session: AsyncSession, day: date) -> None:
        """Make sure today's counter row exists, tolerating a concurrent creator."""
        existing = await session.scalar(select(ApiBudget.id).where(ApiBudget.budget_date == day))
        if existing is not None:
            return
        session.add(ApiBudget(budget_date=day, provider=self._provider, calls_used=0))
        try:
            await session.commit()
        except IntegrityError:
            # Another worker inserted the same day's row first; that is fine.
            await session.rollback()

    async def reserve(self, endpoint: str = "", *, cost: int = 1) -> int:
        """Reserve `cost` calls and return the running total for today.

        Raises BudgetExhausted (without consuming quota) when the ceiling is reached.
        """
        day = utc_today()
        async with self._session_factory() as session:
            await self._ensure_row(session, day)

            stmt = (
                update(ApiBudget)
                .where(
                    ApiBudget.budget_date == day,
                    ApiBudget.calls_used <= self._ceiling - cost,
                )
                .values(calls_used=ApiBudget.calls_used + cost, updated_at=datetime.utcnow())
                .returning(ApiBudget.calls_used)
            )
            calls_used = await session.scalar(stmt)
            await session.commit()

            if calls_used is None:
                used = await self.calls_used_today()
                logger.error(
                    "FMP budget exhausted: %s/%s used, refusing call to %s",
                    used,
                    self._ceiling,
                    endpoint or "<unknown endpoint>",
                )
                raise BudgetExhausted(used, self._ceiling, next_utc_midnight())

            logger.info(
                "FMP call reserved: endpoint=%s calls_used=%s/%s remaining=%s",
                endpoint or "<unknown endpoint>",
                calls_used,
                self._ceiling,
                self._ceiling - calls_used,
            )
            return calls_used

    async def calls_used_today(self) -> int:
        """Calls consumed so far today (0 when nothing has been recorded yet)."""
        async with self._session_factory() as session:
            used = await session.scalar(
                select(ApiBudget.calls_used).where(ApiBudget.budget_date == utc_today())
            )
            return used or 0

    async def remaining_today(self) -> int:
        """Calls still available under the local ceiling."""
        return max(0, self._ceiling - await self.calls_used_today())

    async def check_available(self, needed: int = 1) -> bool:
        """Whether `needed` calls fit under the ceiling, without reserving them.

        Used by the reference pipeline to stop cleanly *before* starting a ticker it
        cannot finish, rather than half-refreshing one.
        """
        return await self.remaining_today() >= needed

    async def history(self, limit: int = 14) -> list[ApiBudget]:
        """Recent daily counters, newest first."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(ApiBudget).order_by(ApiBudget.budget_date.desc()).limit(limit)
            )
            return list(result.scalars().all())


class NullBudgetGuard(DailyBudgetGuard):
    """A guard for paths that make no real API calls (fixture replay).

    Replay never touches the network, so there is no quota to spend. `is_enabled` is
    False so callers report "n/a" rather than a misleading zero-remaining budget.
    """

    def __init__(self) -> None:  # noqa: D107 - deliberately does not call super().__init__
        self._session_factory = None
        self._ceiling = 0
        self._provider = "none"

    @property
    def is_enabled(self) -> bool:
        return False

    async def reserve(self, endpoint: str = "", *, cost: int = 1) -> int:
        return 0

    async def calls_used_today(self) -> int:
        return 0

    async def remaining_today(self) -> int:
        return 0

    async def check_available(self, needed: int = 1) -> bool:
        return True

    async def history(self, limit: int = 14) -> list[ApiBudget]:
        return []
