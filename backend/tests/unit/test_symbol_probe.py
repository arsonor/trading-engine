"""Tests for the free-tier symbol probe.

The probe is what turns "FMP documents ~87 sample symbols" into a concrete universe. Its
one non-negotiable property is that it can detect a NEGATIVE — a probe that marks
everything accessible would hand Phase 2 a universe of tickers that return nothing.
"""

import httpx
import pytest
from sqlalchemy import select

from app.models.universe import Universe
from app.services.fmp.budget import DailyBudgetGuard
from app.services.fmp.client import FmpClient
from app.services.reference.probe import (
    CONTROL_GROUP,
    DEFAULT_CANDIDATES,
    PROBE_CHUNK_SIZE,
    SymbolProber,
)

# Everything the stub serves; anything else is "not on this plan".
SERVED = {"AAPL", "MSFT", "NVDA"}


def stub_client(budget, served=SERVED, calls=None) -> FmpClient:
    def handler(request: httpx.Request) -> httpx.Response:
        requested = request.url.params["symbols"].split(",")
        if calls is not None:
            calls.append(requested)
        return httpx.Response(
            200,
            json=[{"symbol": s, "price": 100.0, "name": f"{s} Inc", "exchange": "NASDAQ"}
                  for s in requested if s in served],
        )

    return FmpClient(
        api_key="test-key",
        base_url="https://fmp.test",
        budget=budget,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


@pytest.fixture
def budget(test_session_factory):
    return DailyBudgetGuard(session_factory=test_session_factory, ceiling=50)


async def test_probe_separates_accessible_from_restricted(budget, test_session_factory):
    prober = SymbolProber(stub_client(budget), session_factory=test_session_factory)
    report = await prober.probe(["AAPL", "MSFT", "NVDA", "SNDL", "MULN"])

    assert report.accessible == ["AAPL", "MSFT", "NVDA"]
    assert report.inaccessible == ["SNDL", "MULN"]
    assert report.universe_size == 3


async def test_probe_detects_a_negative(budget, test_session_factory):
    """If the control group came back accessible, the free-tier model is wrong."""
    prober = SymbolProber(stub_client(budget), session_factory=test_session_factory)
    report = await prober.probe(["AAPL", *sorted(CONTROL_GROUP)])

    assert report.control_accessible == []


async def test_control_group_hit_is_surfaced(budget, test_session_factory):
    served = SERVED | {"SNDL"}
    prober = SymbolProber(stub_client(budget, served), session_factory=test_session_factory)
    report = await prober.probe(["AAPL", "SNDL"])

    assert report.control_accessible == ["SNDL"]


async def test_probe_batches_to_conserve_budget(budget, test_session_factory):
    """One call per chunk — probing 87 candidates must not cost 87 calls."""
    calls: list[list[str]] = []
    prober = SymbolProber(
        stub_client(budget, calls=calls), session_factory=test_session_factory, chunk_size=25
    )
    await prober.probe(DEFAULT_CANDIDATES)

    expected_chunks = -(-len(DEFAULT_CANDIDATES) // PROBE_CHUNK_SIZE)
    assert len(calls) == expected_chunks
    assert await budget.calls_used_today() == expected_chunks


async def test_probe_persists_the_universe(budget, test_session_factory):
    prober = SymbolProber(stub_client(budget), session_factory=test_session_factory)
    await prober.probe(["AAPL", "SNDL"])

    async with test_session_factory() as session:
        accessible = await session.scalar(select(Universe).where(Universe.ticker == "AAPL"))
        blocked = await session.scalar(select(Universe).where(Universe.ticker == "SNDL"))

    assert accessible.is_accessible_free_tier is True
    assert accessible.is_active is True
    assert accessible.name == "AAPL Inc"
    assert accessible.exchange == "NASDAQ"

    # The negative result is kept on record rather than dropped — re-probing later must
    # be able to tell "known inaccessible" from "never tested".
    assert blocked.is_accessible_free_tier is False
    assert blocked.is_active is False
    assert blocked.probe_note


async def test_reprobing_updates_an_existing_row(budget, test_session_factory):
    prober = SymbolProber(stub_client(budget), session_factory=test_session_factory)
    await prober.probe(["SNDL"])

    upgraded = SymbolProber(
        stub_client(budget, SERVED | {"SNDL"}), session_factory=test_session_factory
    )
    await upgraded.probe(["SNDL"])

    async with test_session_factory() as session:
        rows = (await session.execute(select(Universe).where(Universe.ticker == "SNDL"))).scalars()
        rows = list(rows)

    assert len(rows) == 1  # updated, not duplicated
    assert rows[0].is_accessible_free_tier is True


async def test_probe_stops_cleanly_when_budget_runs_out(test_session_factory):
    """A partial probe must still persist what it learned before stopping."""
    guard = DailyBudgetGuard(session_factory=test_session_factory, ceiling=1)
    prober = SymbolProber(stub_client(guard), session_factory=test_session_factory, chunk_size=2)
    report = await prober.probe(["AAPL", "MSFT", "NVDA", "SNDL"])

    assert report.stopped_early
    assert report.accessible == ["AAPL", "MSFT"]

    async with test_session_factory() as session:
        stored = await session.scalar(select(Universe).where(Universe.ticker == "AAPL"))
    assert stored is not None


async def test_rows_without_a_price_are_not_counted_as_accessible(budget, test_session_factory):
    """A placeholder row with no price is not real access to the symbol."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"symbol": "AAPL", "price": None}])

    client = FmpClient(
        api_key="test-key",
        base_url="https://fmp.test",
        budget=budget,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    report = await SymbolProber(client, session_factory=test_session_factory).probe(["AAPL"])

    assert report.accessible == []
    assert report.inaccessible == ["AAPL"]


def free_tier_client(budget, served=SERVED, calls=None) -> FmpClient:
    """A stub matching the live free tier: batch-quote 402s, single quote works."""
    restricted_endpoint = (
        "Restricted Endpoint: This endpoint is not available under your current subscription"
    )
    restricted_symbol = (
        "Premium Query Parameter: 'Special Endpoint : This value set for 'symbol' is not "
        "available under your current subscription"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/batch-quote"):
            return httpx.Response(402, text=restricted_endpoint)
        symbol = request.url.params["symbol"]
        if calls is not None:
            calls.append(symbol)
        if symbol not in served:
            return httpx.Response(402, text=restricted_symbol)
        return httpx.Response(
            200, json=[{"symbol": symbol, "price": 100.0, "name": f"{symbol} Inc"}]
        )

    return FmpClient(
        api_key="test-key",
        base_url="https://fmp.test",
        budget=budget,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )


async def test_probe_falls_back_to_per_symbol_when_batch_is_restricted(
    budget, test_session_factory
):
    """The free tier 402s batch-quote. Falling back is what keeps V1 possible at all."""
    calls: list[str] = []
    prober = SymbolProber(
        free_tier_client(budget, calls=calls), session_factory=test_session_factory
    )
    report = await prober.probe(["AAPL", "MSFT", "SNDL"])

    assert report.mode == "quote (per symbol)"
    assert report.accessible == ["AAPL", "MSFT"]
    assert report.inaccessible == ["SNDL"]
    assert calls == ["AAPL", "MSFT", "SNDL"]
    # One wasted batch attempt, then one call per symbol.
    assert report.calls_used == 4
    assert report.notes and "batch-quote unavailable" in report.notes[0]


async def test_per_symbol_fallback_persists_the_universe(budget, test_session_factory):
    prober = SymbolProber(free_tier_client(budget), session_factory=test_session_factory)
    await prober.probe(["AAPL", "SNDL"])

    assert await prober.accessible_universe() == ["AAPL"]


async def test_per_symbol_fallback_stops_when_budget_runs_out(test_session_factory):
    guard = DailyBudgetGuard(session_factory=test_session_factory, ceiling=3)
    prober = SymbolProber(free_tier_client(guard), session_factory=test_session_factory)
    report = await prober.probe(["AAPL", "MSFT", "NVDA"])

    assert report.stopped_early
    assert report.accessible == ["AAPL", "MSFT"]  # the batch attempt ate the third call
    assert await prober.accessible_universe() == ["AAPL", "MSFT"]


async def test_default_candidate_list_includes_a_control_group():
    assert CONTROL_GROUP.issubset(set(DEFAULT_CANDIDATES))
    assert len(set(DEFAULT_CANDIDATES)) == len(DEFAULT_CANDIDATES)  # no duplicates
