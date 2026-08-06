"""Daily FMP API budget guard, and bandwidth accounting.

Every FMP call goes through `DailyBudgetGuard.reserve()` *before* the HTTP request is
made. The counter is in Postgres, not memory, because cron jobs and the web service are
separate processes and share one quota.

**What the guard is for changed with Premium (Phase 4B).** It was built against the free
tier's 250 calls/day hard 429 — exceed it and everything stops. Premium has no daily call
cap at all (750/min, 50 GB per rolling 30 days), so the ceiling is no longer a vendor limit
being tracked; it is **runaway protection**, there to stop a bug that loops over the
universe from quietly spending the bandwidth allowance.

The number that can actually end a month early is now `bytes_used`, which is why this
module also tracks bandwidth. Calls are *reserved* before a request; bytes are *recorded*
after one, since their size is unknown until the response arrives.

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

from sqlalchemy import func, select, update
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

    async def record_bytes(self, count: int) -> None:
        """Record response bytes for today.

        **Recorded after the fact, not reserved.** Calls are reserved beforehand because
        the ceiling must be enforced before the request goes out; bytes cannot be, because
        the size is unknown until the response arrives. That asymmetry is deliberate — this
        is measurement, not enforcement.

        Failures here are swallowed. Bandwidth accounting must never be the reason a scan
        fails: the number is for the operator, and losing one response's worth of it is
        immaterial next to losing the scan.
        """
        if count <= 0:
            return
        day = utc_today()
        try:
            async with self._session_factory() as session:
                await self._ensure_row(session, day)
                await session.execute(
                    update(ApiBudget)
                    .where(ApiBudget.budget_date == day)
                    .values(
                        bytes_used=ApiBudget.bytes_used + count,
                        updated_at=datetime.utcnow(),
                    )
                )
                await session.commit()
        except Exception:  # noqa: BLE001 - see docstring
            logger.debug("Could not record %s bytes of FMP bandwidth", count, exc_info=True)

    async def bytes_used_today(self) -> int:
        async with self._session_factory() as session:
            used = await session.scalar(
                select(ApiBudget.bytes_used).where(ApiBudget.budget_date == utc_today())
            )
            return used or 0

    async def bytes_used_last_30_days(self) -> int:
        """Bandwidth over the trailing 30 days — the window FMP's 50 GB allowance uses."""
        since = utc_today() - timedelta(days=29)
        async with self._session_factory() as session:
            total = await session.scalar(
                select(func.coalesce(func.sum(ApiBudget.bytes_used), 0)).where(
                    ApiBudget.budget_date >= since
                )
            )
            return int(total or 0)

    async def bandwidth_status(self) -> dict[str, float | int | bool | str]:
        """Bandwidth against the vendor allowance, for reporting.

        Premium has no daily call cap, so this — not `calls_used` — is the number that can
        end a month early. 4A projected ~15% of the allowance at the measured universe
        size, which is comfortable, but a threshold edit can move the universe a long way
        in one night.
        """
        settings = get_settings()
        allowance = int(settings.fmp_monthly_bandwidth_gb * 1_000_000_000)
        used = await self.bytes_used_last_30_days()
        pct = (100.0 * used / allowance) if allowance else 0.0
        return {
            "bytes_today": await self.bytes_used_today(),
            "bytes_30d": used,
            "allowance_bytes": allowance,
            "pct_used": round(pct, 2),
            "over_warn_threshold": pct >= settings.fmp_bandwidth_warn_pct,
            "warn_at_pct": settings.fmp_bandwidth_warn_pct,
        }

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
