"""Integration tests for the reference-data pipeline.

The three properties under test are the ones the free tier forces: budget awareness,
idempotence, and resumability. All data comes from the fixture replay client — no live
FMP call is made here or anywhere else in the suite.
"""

import pytest
from sqlalchemy import select

from app.models.reference_data import ReferenceData
from app.models.universe import Universe
from app.services.fmp.budget import DailyBudgetGuard
from app.services.fmp.errors import BudgetExhausted
from app.services.fmp.fixtures import FixtureFmpClient
from app.services.reference.pipeline import (
    STATUS_FAILED,
    STATUS_REFRESHED,
    STATUS_SKIPPED,
    STATUS_STOPPED,
    STATUS_UNAVAILABLE,
    STATUS_WOULD_REFRESH,
    ReferenceRefresher,
)


@pytest.fixture
def refresher(fixture_fmp_client, test_session_factory):
    return ReferenceRefresher(fixture_fmp_client, session_factory=test_session_factory)


async def read_reference(session_factory, ticker: str) -> ReferenceData | None:
    async with session_factory() as session:
        return await session.scalar(select(ReferenceData).where(ReferenceData.ticker == ticker))


async def test_refresh_computes_and_persists_every_metric(refresher, test_session_factory):
    report = await refresher.run(["AAPL"])

    assert report.count(STATUS_REFRESHED) == 1
    row = await read_reference(test_session_factory, "AAPL")
    assert row is not None
    assert row.static_float == 15_000_000_000
    assert row.outstanding_shares == 15_400_000_000
    assert row.volume_avg_20d == 1_000_000
    assert row.price_close_yesterday == 229.5
    assert row.high_yesterday == 230.5
    assert row.high_20d == 230.5
    assert row.sma_50 == 217.25
    assert row.sma_200 == 179.75
    assert str(row.last_bar_date) == "2026-07-24"
    assert row.bars_used == 260
    assert row.data_source == "fixture"  # never mistakable for live data


async def test_refresh_creates_the_universe_row_if_absent(refresher, test_session_factory):
    await refresher.run(["SMLC"])

    async with test_session_factory() as session:
        row = await session.scalar(select(Universe).where(Universe.ticker == "SMLC"))
    assert row is not None
    assert row.is_accessible_free_tier is True
    assert row.last_refreshed_at is not None


async def test_rerunning_the_same_day_costs_nothing(refresher, test_session_factory):
    """Idempotence is what keeps a re-run from burning a second 2 calls per ticker."""
    first = await refresher.run(["AAPL", "MSFT"])
    assert first.calls_used == 4

    second = await refresher.run(["AAPL", "MSFT"])
    assert second.calls_used == 0
    assert second.count(STATUS_SKIPPED) == 2


async def test_force_overrides_the_same_day_skip(fixture_fmp_client, test_session_factory):
    await ReferenceRefresher(fixture_fmp_client, session_factory=test_session_factory).run(["AAPL"])

    forced = ReferenceRefresher(
        fixture_fmp_client, session_factory=test_session_factory, force=True
    )
    report = await forced.run(["AAPL"])

    assert report.count(STATUS_REFRESHED) == 1


async def test_dry_run_makes_no_calls_and_writes_nothing(
    fixture_fmp_client, test_session_factory
):
    refresher = ReferenceRefresher(
        fixture_fmp_client, session_factory=test_session_factory, dry_run=True
    )
    report = await refresher.run(["AAPL", "MSFT"])

    assert report.count(STATUS_WOULD_REFRESH) == 2
    assert report.calls_used == 0
    assert await read_reference(test_session_factory, "AAPL") is None


async def test_restricted_symbol_is_skipped_and_recorded(refresher, test_session_factory):
    """SymbolNotAvailable is routine on the free tier: skip the ticker, keep going."""
    report = await refresher.run(["SNDL", "AAPL"])

    assert report.count(STATUS_UNAVAILABLE) == 1
    assert report.count(STATUS_REFRESHED) == 1

    async with test_session_factory() as session:
        row = await session.scalar(select(Universe).where(Universe.ticker == "SNDL"))
    assert row.is_accessible_free_tier is False
    assert row.probe_note

    assert await read_reference(test_session_factory, "SNDL") is None


async def test_missing_float_still_persists_the_eod_metrics(refresher, test_session_factory):
    """Losing every price metric because FMP has no float would be a bad trade."""
    report = await refresher.run(["NOFLT"])

    assert report.count(STATUS_REFRESHED) == 1
    row = await read_reference(test_session_factory, "NOFLT")
    assert row.static_float is None
    assert row.volume_avg_20d == 1_000_000


async def test_malformed_response_fails_only_that_ticker(refresher, test_session_factory):
    report = await refresher.run(["BROKEN", "AAPL"])

    assert report.count(STATUS_FAILED) == 1
    assert report.count(STATUS_REFRESHED) == 1
    assert await read_reference(test_session_factory, "AAPL") is not None


async def test_budget_exhaustion_stops_cleanly_with_progress_preserved(
    fmp_fixture_store, test_session_factory
):
    """Three calls of ceiling means one full ticker (2 calls) and a clean stop before
    the second — never a half-refreshed row."""
    client = FixtureFmpClient(
        store=fmp_fixture_store,
        budget=DailyBudgetGuard(session_factory=test_session_factory, ceiling=3),
    )

    refresher = ReferenceRefresher(client, session_factory=test_session_factory)
    report = await refresher.run(["AAPL", "MSFT", "SMLC"])

    assert report.stopped_early
    assert report.count(STATUS_STOPPED) == 1
    assert report.count(STATUS_REFRESHED) == 1

    assert await read_reference(test_session_factory, "AAPL") is not None
    assert await read_reference(test_session_factory, "MSFT") is None
    assert await read_reference(test_session_factory, "SMLC") is None


async def test_resuming_after_a_stop_continues_where_it_left_off(
    fmp_fixture_store, test_session_factory
):
    tight = FixtureFmpClient(
        store=fmp_fixture_store,
        budget=DailyBudgetGuard(session_factory=test_session_factory, ceiling=3),
    )
    await ReferenceRefresher(tight, session_factory=test_session_factory).run(["AAPL", "MSFT"])

    # Next day / raised ceiling: the finished ticker is skipped, the unfinished one runs.
    roomy = FixtureFmpClient(
        store=fmp_fixture_store,
        budget=DailyBudgetGuard(session_factory=test_session_factory, ceiling=100),
    )
    report = await ReferenceRefresher(roomy, session_factory=test_session_factory).run(
        ["AAPL", "MSFT"]
    )

    assert report.count(STATUS_SKIPPED) == 1
    assert report.count(STATUS_REFRESHED) == 1
    assert await read_reference(test_session_factory, "MSFT") is not None


async def test_active_tickers_excludes_known_inaccessible_symbols(
    refresher, test_session_factory
):
    async with test_session_factory() as session:
        session.add_all(
            [
                Universe(ticker="AAPL", is_active=True, is_accessible_free_tier=True),
                Universe(ticker="SNDL", is_active=False, is_accessible_free_tier=False),
                # Never probed — unknown is not the same as known-bad, so it is included.
                Universe(ticker="MSFT", is_active=True, is_accessible_free_tier=None),
            ]
        )
        await session.commit()

    assert await refresher.active_tickers() == ["AAPL", "MSFT"]


async def test_budget_guard_refuses_before_any_work_when_fully_exhausted(
    fmp_fixture_store, test_session_factory
):
    guard = DailyBudgetGuard(session_factory=test_session_factory, ceiling=1)
    await guard.reserve("warmup")
    with pytest.raises(BudgetExhausted):
        await guard.reserve("warmup")

    client = FixtureFmpClient(store=fmp_fixture_store, budget=guard)
    report = await ReferenceRefresher(client, session_factory=test_session_factory).run(["AAPL"])

    assert report.stopped_early
    assert report.count(STATUS_REFRESHED) == 0
