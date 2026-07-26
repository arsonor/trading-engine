"""Typed errors for the FMP data provider.

The taxonomy exists so callers can make the one decision that matters on a metered free
tier: *stop* (BudgetExhausted, RateLimited, AuthFailed), *skip this ticker*
(SymbolNotAvailable, MalformedResponse) or *retry* (TransientError).
"""

from datetime import datetime


class FmpError(Exception):
    """Base class for every FMP-related failure."""


class BudgetExhausted(FmpError):
    """The local daily budget ceiling was reached; the call was never made.

    This is the guard firing *before* FMP's own 250/day cap, so no quota was spent.
    """

    def __init__(self, calls_used: int, ceiling: int, resets_at: datetime) -> None:
        self.calls_used = calls_used
        self.ceiling = ceiling
        self.resets_at = resets_at
        super().__init__(
            f"Daily FMP budget exhausted: {calls_used}/{ceiling} calls used. "
            f"Budget resets at {resets_at.isoformat()} (00:00 UTC). "
            f"Raise FMP_DAILY_BUDGET only if the provider cap allows it."
        )


class RateLimited(FmpError):
    """FMP returned HTTP 429.

    On the free tier this means the real daily cap is gone. It is never retried —
    retrying a daily-cap 429 cannot succeed and only adds load.
    """

    def __init__(self, message: str = "FMP returned 429 (rate limited / daily cap reached)") -> None:
        super().__init__(message)


class AuthFailed(FmpError):
    """The API key is missing, invalid, or lacks the plan for this endpoint (401/403)."""


class SymbolNotAvailable(FmpError):
    """The symbol is not served to this API key/plan, or returned no data.

    Expected and routine on the free tier, whose sample is ~87 large-cap symbols.
    """

    def __init__(self, symbol: str, detail: str = "") -> None:
        self.symbol = symbol
        self.detail = detail
        message = f"Symbol {symbol!r} is not available on this FMP plan"
        if detail:
            message = f"{message}: {detail}"
        super().__init__(message)


class TransientError(FmpError):
    """A network error or 5xx — the only class of failure worth retrying."""


class MalformedResponse(FmpError):
    """The response was not shaped the way the documented schema promises."""


class FeatureRequiresIntraday(FmpError):
    """A calculation needs intraday data the current FMP tier does not provide."""
