"""Tests for the FMP client's transport behaviour.

All requests are served by an httpx MockTransport — no network, no live FMP, ever.
The behaviours under test are the ones that cost real money or real quota when wrong:
what gets retried, what does not, and how many budget units each path spends.
"""

import httpx
import pytest

from app.services.fmp.budget import DailyBudgetGuard
from app.services.fmp.client import FmpClient
from app.services.fmp.errors import (
    AuthFailed,
    BudgetExhausted,
    MalformedResponse,
    RateLimited,
    SymbolNotAvailable,
    TransientError,
)

EOD_ROWS = [
    {"date": "2026-07-24", "open": 100.0, "high": 105.0, "low": 99.0, "close": 104.0,
     "volume": 1_000_000},
    {"date": "2026-07-23", "open": 98.0, "high": 101.0, "low": 97.0, "close": 100.0,
     "volume": 900_000},
]


def build_client(handler, budget, **kwargs) -> FmpClient:
    transport = httpx.MockTransport(handler)
    kwargs.setdefault("retry_backoff_seconds", 0.0)  # keep retry tests instant
    return FmpClient(
        api_key="test-key",
        base_url="https://fmp.test",
        budget=budget,
        http_client=httpx.AsyncClient(transport=transport),
        **kwargs,
    )


@pytest.fixture
def budget(test_session_factory):
    return DailyBudgetGuard(session_factory=test_session_factory, ceiling=10)


async def test_get_eod_history_parses_and_sorts_newest_first(budget):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["symbol"] == "AAPL"
        assert request.url.params["apikey"] == "test-key"
        # Deliberately oldest-first to prove the client normalizes the order.
        return httpx.Response(200, json=list(reversed(EOD_ROWS)))

    client = build_client(handler, budget)
    bars = await client.get_eod_history("AAPL")

    assert [str(b.date) for b in bars] == ["2026-07-24", "2026-07-23"]
    assert bars[0].close == 104.0
    assert await budget.calls_used_today() == 1


async def test_calls_go_through_the_budget_guard(test_session_factory):
    """The guard is not advisory: with no budget left, no HTTP request is made."""
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(200, json=EOD_ROWS)

    tight = DailyBudgetGuard(session_factory=test_session_factory, ceiling=1)
    client = build_client(handler, tight)

    await client.get_eod_history("AAPL")
    with pytest.raises(BudgetExhausted):
        await client.get_eod_history("MSFT")

    assert calls["n"] == 1


async def test_transient_5xx_is_retried_then_succeeds(budget):
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json=EOD_ROWS)

    client = build_client(handler, budget)
    bars = await client.get_eod_history("AAPL")

    assert len(bars) == 2
    assert attempts["n"] == 3
    # Every attempt is a real call against the quota, so all three are counted.
    assert await budget.calls_used_today() == 3


async def test_transient_failure_raises_after_max_retries(budget):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = build_client(handler, budget)
    with pytest.raises(TransientError):
        await client.get_eod_history("AAPL")


async def test_429_is_never_retried(budget):
    """A daily-cap 429 cannot be retried into success — retrying only adds load."""
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(429, json={"Error Message": "Limit Reach . Please upgrade"})

    client = build_client(handler, budget)
    with pytest.raises(RateLimited):
        await client.get_eod_history("AAPL")

    assert attempts["n"] == 1


async def test_restricted_symbol_raises_symbol_not_available(budget):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            403, json={"Error Message": "This endpoint is limited to the following symbols"}
        )

    client = build_client(handler, budget)
    with pytest.raises(SymbolNotAvailable):
        await client.get_eod_history("SNDL")


async def test_empty_history_is_symbol_not_available(budget):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[])

    client = build_client(handler, budget)
    with pytest.raises(SymbolNotAvailable):
        await client.get_eod_history("NOPE")


async def test_malformed_row_raises_malformed_response(budget):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"date": "2026-07-24", "high": "not-a-number"}])

    client = build_client(handler, budget)
    with pytest.raises(MalformedResponse):
        await client.get_eod_history("AAPL")


async def test_non_json_body_on_a_200_raises_malformed_response(budget):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>gateway</html>")

    client = build_client(handler, budget)
    with pytest.raises(MalformedResponse):
        await client.get_eod_history("AAPL")


async def test_plain_text_402_is_classified_not_treated_as_malformed(budget):
    """The live free tier returns its plan restrictions as bare text, not JSON. Reading
    that as 'malformed' would turn 'skip this ticker' into 'something is broken'."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            text=(
                "Premium Query Parameter: 'Special Endpoint : This value set for 'symbol' "
                "is not available under your current subscription"
            ),
        )

    client = build_client(handler, budget)
    with pytest.raises(SymbolNotAvailable):
        await client.get_eod_history("SNDL")


async def test_plain_text_402_endpoint_restriction_is_auth_failed(budget):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            402,
            text=(
                "Restricted Endpoint: This endpoint is not available under your current "
                "subscription please visit our subscription page"
            ),
        )

    client = build_client(handler, budget)
    with pytest.raises(AuthFailed):
        await client.get_batch_quotes(["AAPL", "MSFT"])


async def test_missing_api_key_fails_before_spending_budget(test_session_factory):
    guard = DailyBudgetGuard(session_factory=test_session_factory, ceiling=10)
    client = FmpClient(api_key="", base_url="https://fmp.test", budget=guard)

    with pytest.raises(AuthFailed):
        await client.get_quote("AAPL")
    assert await guard.calls_used_today() == 0


async def test_shares_float_tolerates_missing_float_figures(budget):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=[{"symbol": "AAPL", "date": "2026-07-24"}])

    client = build_client(handler, budget)
    shares = await client.get_shares_float("AAPL")

    assert shares.symbol == "AAPL"
    assert shares.float_shares is None
    assert shares.outstanding_shares is None


async def test_batch_quote_is_one_call_for_many_symbols(budget):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["symbols"] == "AAPL,MSFT,SNDL"
        # SNDL is absent — that is how the free tier says "not served".
        return httpx.Response(
            200,
            json=[{"symbol": "AAPL", "price": 210.0}, {"symbol": "MSFT", "price": 420.0}],
        )

    client = build_client(handler, budget)
    quotes = await client.get_batch_quotes(["AAPL", "MSFT", "SNDL"])

    assert [q.symbol for q in quotes] == ["AAPL", "MSFT"]
    assert await budget.calls_used_today() == 1


async def test_batch_quote_with_no_symbols_makes_no_call(budget):
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("no request expected")

    client = build_client(handler, budget)
    assert await client.get_batch_quotes([]) == []
    assert await budget.calls_used_today() == 0
