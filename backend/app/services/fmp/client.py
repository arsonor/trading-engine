"""Async FMP client for the `stable/` API.

Design constraints that come from the free (Basic) tier, not from taste:
  * Every request reserves a call from `DailyBudgetGuard` BEFORE it goes out. Retries
    reserve again, because a retry is a real call against the quota.
  * 429 is never retried. On this tier it means the daily cap is gone; retrying cannot
    succeed. Only 5xx and network failures are retried.
  * The symbol sample is small, so `SymbolNotAvailable` is an ordinary outcome that
    callers skip past, not a crash.
"""

import asyncio
import logging
from typing import Any

import httpx

from app.config import get_settings
from app.services.fmp.budget import DailyBudgetGuard
from app.services.fmp.errors import (
    AuthFailed,
    MalformedResponse,
    SymbolNotAvailable,
    TransientError,
)
from app.services.fmp.models import CompanyProfile, EodBar, Quote, SharesFloat
from app.services.fmp.parsing import RawResponse, as_list, interpret

logger = logging.getLogger(__name__)

# Endpoint paths under `<base>/stable/`.
EP_EOD_FULL = "historical-price-eod/full"
EP_SHARES_FLOAT = "shares-float"
EP_QUOTE = "quote"
EP_BATCH_QUOTE = "batch-quote"
EP_PROFILE = "profile"
EP_STOCK_LIST = "stock-list"
EP_SCREENER = "company-screener"


class FmpClient:
    """Budget-guarded async client for the FMP stable API."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        budget: DailyBudgetGuard | None = None,
        http_client: httpx.AsyncClient | None = None,
        max_retries: int | None = None,
        retry_backoff_seconds: float | None = None,
    ) -> None:
        settings = get_settings()
        self._api_key = api_key if api_key is not None else settings.fmp_api_key
        self._base_url = (base_url or settings.fmp_base_url).rstrip("/")
        self._budget = budget or DailyBudgetGuard()
        self._timeout = settings.fmp_timeout_seconds
        self._max_retries = settings.fmp_max_retries if max_retries is None else max_retries
        self._backoff = (
            settings.fmp_retry_backoff_seconds
            if retry_backoff_seconds is None
            else retry_backoff_seconds
        )
        self._client = http_client
        self._owns_client = http_client is None

    @property
    def budget(self) -> DailyBudgetGuard:
        return self._budget

    async def __aenter__(self) -> "FmpClient":
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    # ------------------------------------------------------------------ transport

    async def _raw_get(self, endpoint: str, params: dict[str, Any]) -> RawResponse:
        """Perform one budget-guarded GET, retrying transient failures only.

        Overridden by the fixture client — which is why every public method below is
        written against this single seam.
        """
        if not self._api_key:
            raise AuthFailed("FMP_API_KEY is not set; refusing to call FMP without a key.")

        url = f"{self._base_url}/stable/{endpoint}"
        query = {**params, "apikey": self._api_key}
        last_error: Exception | None = None

        for attempt in range(1, self._max_retries + 1):
            # Reserve per attempt: a retry consumes real quota, so it must be counted.
            await self._budget.reserve(endpoint)
            try:
                response = await self._http().get(url, params=query)
            except httpx.HTTPError as exc:
                last_error = TransientError(f"Network error calling {endpoint}: {exc}")
            else:
                if response.status_code < 500:
                    return RawResponse(response.status_code, _safe_json(response, endpoint))
                last_error = TransientError(
                    f"FMP returned HTTP {response.status_code} on {endpoint}"
                )

            if attempt < self._max_retries:
                delay = self._backoff * (2 ** (attempt - 1))
                logger.warning(
                    "Transient FMP failure on %s (attempt %s/%s): %s — retrying in %.1fs",
                    endpoint,
                    attempt,
                    self._max_retries,
                    last_error,
                    delay,
                )
                await asyncio.sleep(delay)

        assert last_error is not None
        raise last_error

    async def _get(
        self, endpoint: str, params: dict[str, Any], *, symbol: str | None = None
    ) -> Any:
        raw = await self._raw_get(endpoint, params)
        return interpret(raw, endpoint=endpoint, symbol=symbol)

    # --------------------------------------------------------------- public API

    async def get_eod_history(self, symbol: str, *, limit: int | None = None) -> list[EodBar]:
        """Full daily history for a symbol — ONE call yields every EOD-derived metric.

        Bars are returned newest-first, matching FMP, because every consumer wants the
        recent window.
        """
        params: dict[str, Any] = {"symbol": symbol}
        payload = await self._get(EP_EOD_FULL, params, symbol=symbol)
        rows = as_list(payload, endpoint=EP_EOD_FULL)
        if not rows:
            raise SymbolNotAvailable(symbol, "empty EOD history")

        bars = [_validate(EodBar, row, EP_EOD_FULL) for row in rows]
        bars.sort(key=lambda b: b.date, reverse=True)
        return bars[:limit] if limit else bars

    async def get_shares_float(self, symbol: str) -> SharesFloat:
        """Float/outstanding shares. Fields may be None — FMP lacks float for some names."""
        payload = await self._get(EP_SHARES_FLOAT, {"symbol": symbol}, symbol=symbol)
        rows = as_list(payload, endpoint=EP_SHARES_FLOAT)
        if not rows:
            raise SymbolNotAvailable(symbol, "empty shares-float response")
        return _validate(SharesFloat, rows[0], EP_SHARES_FLOAT)

    async def get_quote(self, symbol: str) -> Quote:
        """Single-symbol quote snapshot."""
        payload = await self._get(EP_QUOTE, {"symbol": symbol}, symbol=symbol)
        rows = as_list(payload, endpoint=EP_QUOTE)
        if not rows:
            raise SymbolNotAvailable(symbol, "empty quote response")
        return _validate(Quote, rows[0], EP_QUOTE)

    async def get_batch_quotes(self, symbols: list[str]) -> list[Quote]:
        """Quotes for many symbols in ONE call — the cheapest way to probe availability.

        Symbols the plan cannot serve are simply absent from the response; the caller
        diffs requested against returned rather than getting an error per symbol.
        """
        if not symbols:
            return []
        payload = await self._get(EP_BATCH_QUOTE, {"symbols": ",".join(symbols)})
        rows = as_list(payload, endpoint=EP_BATCH_QUOTE)
        return [_validate(Quote, row, EP_BATCH_QUOTE) for row in rows]

    async def get_profile(self, symbol: str) -> CompanyProfile:
        """Company profile (name, exchange, sector)."""
        payload = await self._get(EP_PROFILE, {"symbol": symbol}, symbol=symbol)
        rows = as_list(payload, endpoint=EP_PROFILE)
        if not rows:
            raise SymbolNotAvailable(symbol, "empty profile response")
        return _validate(CompanyProfile, rows[0], EP_PROFILE)

    async def get_stock_list(self) -> list[dict[str, Any]]:
        """Full symbol directory. Often plan-restricted — probe, do not assume."""
        payload = await self._get(EP_STOCK_LIST, {})
        return as_list(payload, endpoint=EP_STOCK_LIST)

    async def screen(self, **criteria: Any) -> list[dict[str, Any]]:
        """Company screener. Often plan-restricted on free — probe, do not assume."""
        payload = await self._get(EP_SCREENER, {k: v for k, v in criteria.items() if v is not None})
        return as_list(payload, endpoint=EP_SCREENER)


def _safe_json(response: httpx.Response, endpoint: str) -> Any:
    """Parse the body, keeping plain-text errors classifiable.

    FMP returns its 402 plan restrictions as bare text, not JSON — treating those as
    malformed would turn "skip this ticker" into "something is broken". Non-JSON on a
    200, though, really is malformed.
    """
    try:
        return response.json()
    except ValueError as exc:
        if response.is_success:
            raise MalformedResponse(
                f"{endpoint} returned non-JSON body (HTTP {response.status_code}): "
                f"{response.text[:200]!r}"
            ) from exc
        return {"Error Message": response.text.strip()[:500]}


def _validate(model: type, row: Any, endpoint: str):
    """Validate one row, converting pydantic failures into MalformedResponse."""
    from pydantic import ValidationError

    if not isinstance(row, dict):
        raise MalformedResponse(f"{endpoint} row is {type(row).__name__}, expected object: {row!r}")
    try:
        return model.model_validate(row)
    except ValidationError as exc:
        raise MalformedResponse(f"{endpoint} row failed validation: {exc}") from exc
