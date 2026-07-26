"""Tests for the daily FMP API budget guard.

The guard is the one component that must never be wrong in the permissive direction:
over-counting wastes a few calls, under-counting hits FMP's hard 250/day 429.
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.api_budget import ApiBudget
from app.services.fmp.budget import (
    DailyBudgetGuard,
    NullBudgetGuard,
    next_utc_midnight,
    utc_today,
)
from app.services.fmp.errors import BudgetExhausted


@pytest.fixture
def guard(test_session_factory):
    return DailyBudgetGuard(session_factory=test_session_factory, ceiling=5)


async def test_reserve_increments_and_returns_running_total(guard):
    assert await guard.reserve("quote") == 1
    assert await guard.reserve("quote") == 2
    assert await guard.calls_used_today() == 2
    assert await guard.remaining_today() == 3


async def test_reserve_raises_when_ceiling_reached(guard):
    for _ in range(5):
        await guard.reserve("quote")

    with pytest.raises(BudgetExhausted) as exc_info:
        await guard.reserve("quote")

    error = exc_info.value
    assert error.calls_used == 5
    assert error.ceiling == 5
    assert "resets at" in str(error).lower()


async def test_exhausted_budget_does_not_over_count(guard):
    """A refused call must not consume quota — the request was never made."""
    for _ in range(5):
        await guard.reserve("quote")

    for _ in range(3):
        with pytest.raises(BudgetExhausted):
            await guard.reserve("quote")

    assert await guard.calls_used_today() == 5


async def test_multi_call_reservation_is_all_or_nothing(test_session_factory):
    """A 2-call reservation with 1 call left must fail without consuming that call."""
    guard = DailyBudgetGuard(session_factory=test_session_factory, ceiling=3)
    await guard.reserve("quote", cost=2)

    with pytest.raises(BudgetExhausted):
        await guard.reserve("eod", cost=2)

    assert await guard.calls_used_today() == 2


async def test_check_available_does_not_reserve(guard):
    assert await guard.check_available(5) is True
    assert await guard.calls_used_today() == 0

    await guard.reserve("quote")
    assert await guard.check_available(5) is False
    assert await guard.check_available(4) is True


async def test_counter_is_keyed_on_utc_date(guard, db_session):
    """FMP's quota resets at 00:00 UTC, so the counter must be keyed on the UTC day."""
    await guard.reserve("quote")

    calls_used = await db_session.scalar(
        select(ApiBudget.calls_used).where(ApiBudget.budget_date == utc_today())
    )
    assert calls_used == 1


async def test_next_utc_midnight_is_the_next_day_boundary():
    now = datetime(2026, 7, 25, 14, 30, tzinfo=timezone.utc)
    assert next_utc_midnight(now) == datetime(2026, 7, 26, 0, 0, tzinfo=timezone.utc)


async def test_null_guard_never_blocks_and_reports_disabled():
    guard = NullBudgetGuard()
    assert guard.is_enabled is False
    assert await guard.reserve("quote") == 0
    assert await guard.check_available(1000) is True
    assert await guard.calls_used_today() == 0
