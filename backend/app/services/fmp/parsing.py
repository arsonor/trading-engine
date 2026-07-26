"""Shared response interpretation for live and replayed FMP responses.

Live calls and fixture replays run through exactly this code, so a fixture-backed test
exercises the same classification the production path uses. If the two diverged, tests
would be validating a parser that never runs in anger.
"""

from dataclasses import dataclass
from typing import Any

from app.services.fmp.errors import (
    AuthFailed,
    MalformedResponse,
    RateLimited,
    SymbolNotAvailable,
    TransientError,
)

# FMP puts its human-readable failures in this key, sometimes alongside HTTP 200.
ERROR_KEYS = ("Error Message", "error", "message")

# Verified against a live free-tier key (July 2026). FMP returns HTTP 402 for BOTH kinds
# of plan restriction and distinguishes them only in the message body:
#
#   endpoint-level : "Restricted Endpoint: This endpoint is not available under your
#                     current subscription..."   — stock-list, company-screener, batch-quote
#   symbol-level   : "Premium Query Parameter: 'Special Endpoint : This value set for
#                     'symbol' is not available..." — any ticker outside the free sample
#
# Both messages contain "not available under your current subscription", so only the
# endpoint-specific phrasing can be matched on.
PLAN_ENDPOINT_MARKERS = (
    "restricted endpoint",
    "exclusive endpoint",
    "legacy endpoint",
    "this endpoint is not available",
)


@dataclass(frozen=True)
class RawResponse:
    """An HTTP response reduced to what classification needs."""

    status: int
    payload: Any


def extract_error_message(payload: Any) -> str | None:
    """Pull FMP's error string out of a payload, if there is one."""
    if isinstance(payload, dict):
        for key in ERROR_KEYS:
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return None


def interpret(raw: RawResponse, *, endpoint: str, symbol: str | None = None) -> Any:
    """Turn a raw response into a payload or the right typed error.

    Note that FMP signals plan restrictions in two different ways — an HTTP status *and*
    an "Error Message" body that can arrive with a 200 — so both are inspected.
    """
    message = extract_error_message(raw.payload)
    lowered = (message or "").lower()

    if raw.status == 429 or "limit reach" in lowered:
        raise RateLimited(
            f"FMP rate limit hit on {endpoint}"
            + (f": {message}" if message else " (HTTP 429, daily cap reached)")
        )

    if raw.status == 401 or "invalid api key" in lowered:
        raise AuthFailed(f"FMP rejected the API key on {endpoint}: {message or raw.status}")

    if raw.status in (402, 403) or message:
        # Endpoint restriction fails the whole code path; symbol restriction just means
        # "skip this ticker". FMP returns 402 for both, so the message decides.
        if any(marker in lowered for marker in PLAN_ENDPOINT_MARKERS):
            raise AuthFailed(f"FMP plan does not allow {endpoint}: {message or raw.status}")
        if symbol is not None:
            raise SymbolNotAvailable(symbol, message or f"HTTP {raw.status}")
        raise AuthFailed(f"FMP refused {endpoint}: {message or raw.status}")

    if raw.status >= 500:
        raise TransientError(f"FMP returned HTTP {raw.status} on {endpoint}")

    if raw.status != 200:
        raise MalformedResponse(f"Unexpected HTTP {raw.status} from {endpoint}")

    return raw.payload


def as_list(payload: Any, *, endpoint: str, historical_key: str = "historical") -> list[Any]:
    """Normalize FMP's list-or-wrapped-list responses to a plain list.

    `stable/` returns bare arrays; some endpoints still wrap them under `historical`.
    """
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        inner = payload.get(historical_key)
        if isinstance(inner, list):
            return inner
    raise MalformedResponse(
        f"Expected a list from {endpoint}, got {type(payload).__name__}: {payload!r:.200}"
    )
