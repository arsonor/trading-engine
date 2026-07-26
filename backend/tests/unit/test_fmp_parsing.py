"""Tests for FMP response classification.

FMP signals failure inconsistently — sometimes an HTTP status, sometimes an "Error
Message" body carried by a 200. Getting this wrong on the free tier means either
retrying a daily-cap 429 or treating a plan restriction as a data problem.
"""

import pytest

from app.services.fmp.errors import (
    AuthFailed,
    MalformedResponse,
    RateLimited,
    SymbolNotAvailable,
    TransientError,
)
from app.services.fmp.parsing import RawResponse, as_list, extract_error_message, interpret


def test_success_returns_payload_untouched():
    payload = [{"symbol": "AAPL", "price": 210.0}]
    assert interpret(RawResponse(200, payload), endpoint="quote") is payload


def test_http_429_is_rate_limited():
    with pytest.raises(RateLimited):
        interpret(RawResponse(429, {}), endpoint="quote")


def test_limit_reach_message_on_200_is_rate_limited():
    """FMP sometimes reports the daily cap in the body of a 200 — still a stop signal."""
    payload = {"Error Message": "Limit Reach . Please upgrade your plan"}
    with pytest.raises(RateLimited):
        interpret(RawResponse(200, payload), endpoint="quote", symbol="AAPL")


def test_401_is_auth_failed():
    with pytest.raises(AuthFailed):
        interpret(RawResponse(401, {"Error Message": "Invalid API KEY"}), endpoint="quote")


def test_402_symbol_restriction_is_symbol_not_available():
    """The live free tier's actual answer for a ticker outside its sample."""
    payload = {
        "Error Message": (
            "Premium Query Parameter: 'Special Endpoint : This value set for 'symbol' is not "
            "available under your current subscription please visit our subscription page"
        )
    }
    with pytest.raises(SymbolNotAvailable) as exc_info:
        interpret(RawResponse(402, payload), endpoint="quote", symbol="SNDL")
    assert exc_info.value.symbol == "SNDL"


def test_402_endpoint_restriction_is_auth_failed_even_with_a_symbol():
    """Both restrictions are 402 and both say 'not available under your current
    subscription' — only the endpoint-level phrasing may fail the whole path."""
    payload = {
        "Error Message": (
            "Restricted Endpoint: This endpoint is not available under your current "
            "subscription please visit our subscription page"
        )
    }
    with pytest.raises(AuthFailed):
        interpret(RawResponse(402, payload), endpoint="batch-quote")
    with pytest.raises(AuthFailed):
        interpret(RawResponse(402, payload), endpoint="quote", symbol="AAPL")


def test_403_with_symbol_is_symbol_not_available():
    """A per-symbol restriction is skippable; the run continues with other tickers."""
    payload = {"Error Message": "This endpoint is limited to the following symbols: AAPL, MSFT"}
    with pytest.raises(SymbolNotAvailable) as exc_info:
        interpret(RawResponse(403, payload), endpoint="shares-float", symbol="SNDL")
    assert exc_info.value.symbol == "SNDL"


def test_403_without_symbol_is_auth_failed():
    """A plan-level endpoint restriction is not skippable — it fails the whole path."""
    payload = {"Error Message": "Exclusive Endpoint: This endpoint is not available under your "}
    with pytest.raises(AuthFailed):
        interpret(RawResponse(403, payload), endpoint="company-screener")


def test_500_is_transient():
    with pytest.raises(TransientError):
        interpret(RawResponse(503, {}), endpoint="quote")


def test_unexpected_status_is_malformed():
    with pytest.raises(MalformedResponse):
        interpret(RawResponse(302, {}), endpoint="quote")


def test_extract_error_message_ignores_non_error_payloads():
    assert extract_error_message([{"symbol": "AAPL"}]) is None
    assert extract_error_message({"symbol": "AAPL"}) is None
    assert extract_error_message({"Error Message": "nope"}) == "nope"


def test_as_list_accepts_bare_and_wrapped_arrays():
    assert as_list([1, 2], endpoint="eod") == [1, 2]
    assert as_list({"historical": [1]}, endpoint="eod") == [1]


def test_as_list_rejects_unexpected_shapes():
    with pytest.raises(MalformedResponse):
        as_list("not a list", endpoint="eod")
