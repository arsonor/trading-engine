"""Nightly reference-data pipeline.

Originally two FMP calls per ticker — `historical-price-eod/full` and `shares-float` —
sized against the free tier's 250 calls/day, which funded roughly 80–100 tickers.

**Phase 4B changed both halves of that arithmetic.** Float now arrives from
`shares-float-all`, one bulk fetch of ~8 calls covering the entire market, so the
per-ticker cost drops to a single EOD call. And the EOD request is bounded server-side to
`reference_history_days`, because the deepest metric computed here is SMA-200 and the
endpoint otherwise returns five years: measured at 231 KB -> 51 KB per ticker, which across
a 3,948-ticker universe is the difference between 19.2 GB and 4.2 GB per month against a
50 GB allowance. On Premium bytes are the binding limit, not calls.

Three properties matter more than speed here:

  * **Budget-aware** — remaining budget is checked BEFORE a ticker starts, so a run never
    leaves a ticker half-refreshed (EOD written, float missing) just because the ceiling
    landed mid-ticker.
  * **Idempotent** — a ticker already refreshed today is skipped, so re-running the same
    day costs ~0 calls. `--force` overrides.
  * **Resumable** — every ticker commits on its own. A crash or an exhausted budget
    leaves the completed work intact and the rest simply undone.
"""

import logging
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.reference_data import ReferenceData
from app.models.universe import Universe
from app.services.fmp.budget import utc_today
from app.services.fmp.client import FmpClient
from app.services.fmp.errors import (
    BudgetExhausted,
    FmpError,
    RateLimited,
    SymbolNotAvailable,
)
from app.services.fmp.fixtures import FixtureFmpClient
from app.services.reference.metrics import ReferenceMetrics, compute_reference_metrics

logger = logging.getLogger(__name__)

# eod/full + shares-float, when float is fetched per ticker. Keep in sync with
# `refresh_ticker` below.
CALLS_PER_TICKER = 2
# With a bulk float lookup supplied (Phase 4B), only eod/full is needed per ticker.
# `shares-float-all` costs ~8 calls for the WHOLE market, so at any universe above a
# handful of names this halves the nightly cost: 3,948 tickers drop from 7,896 calls to
# 3,948 + 8.
CALLS_PER_TICKER_BULK_FLOAT = 1

STATUS_REFRESHED = "refreshed"
STATUS_SKIPPED = "skipped"
STATUS_UNAVAILABLE = "unavailable"
STATUS_FAILED = "failed"
STATUS_STOPPED = "stopped"
STATUS_WOULD_REFRESH = "would_refresh"


@dataclass
class TickerResult:
    """Outcome for a single ticker."""

    ticker: str
    status: str
    calls_used: int = 0
    detail: str = ""
    duration_s: float = 0.0


@dataclass
class RefreshReport:
    """Aggregate outcome of one pipeline run."""

    results: list[TickerResult] = field(default_factory=list)
    stopped_early: bool = False
    stop_reason: str = ""

    @property
    def calls_used(self) -> int:
        return sum(r.calls_used for r in self.results)

    def count(self, status: str) -> int:
        return sum(1 for r in self.results if r.status == status)

    def by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for result in self.results:
            counts[result.status] = counts.get(result.status, 0) + 1
        return counts


class ReferenceRefresher:
    """Refreshes `reference_data` for a set of tickers."""

    def __init__(
        self,
        client: FmpClient,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        *,
        force: bool = False,
        dry_run: bool = False,
        float_lookup: Mapping[str, Any] | None = None,
    ) -> None:
        if session_factory is None:
            from app.core.database import async_session_maker

            session_factory = async_session_maker
        self._client = client
        self._session_factory = session_factory
        self._force = force
        self._dry_run = dry_run
        # When present, float comes from one bulk fetch instead of a call per ticker.
        # Anything with `.float_shares` / `.outstanding_shares` works, which is why the
        # bulk row type and the single-symbol type are interchangeable here.
        self._float_lookup = float_lookup

    @property
    def calls_per_ticker(self) -> int:
        return CALLS_PER_TICKER_BULK_FLOAT if self._float_lookup is not None else CALLS_PER_TICKER

    async def active_tickers(self, limit: int | None = None) -> list[str]:
        """Universe tickers eligible for refresh: active and accessible on this plan.

        `is_accessible_free_tier IS NULL` (never probed) is included — an unprobed ticker
        is unknown, not known-bad, and the refresh itself will settle it.
        """
        async with self._session_factory() as session:
            stmt = (
                select(Universe.ticker)
                .where(
                    Universe.is_active.is_(True),
                    Universe.is_accessible_free_tier.isnot(False),
                )
                .order_by(Universe.ticker)
            )
            if limit:
                stmt = stmt.limit(limit)
            return list((await session.execute(stmt)).scalars().all())

    async def run(self, tickers: list[str]) -> RefreshReport:
        """Refresh each ticker in turn, stopping cleanly if the budget runs out."""
        report = RefreshReport()

        for ticker in tickers:
            if not self._dry_run and not await self._client.budget.check_available(
                self.calls_per_ticker
            ):
                remaining = await self._client.budget.remaining_today()
                report.stopped_early = True
                report.stop_reason = (
                    f"Daily budget nearly exhausted: {remaining} call(s) left, "
                    f"{self.calls_per_ticker} needed per ticker. Stopped before {ticker}."
                )
                logger.warning(report.stop_reason)
                report.results.append(
                    TickerResult(ticker, STATUS_STOPPED, detail=report.stop_reason)
                )
                break

            result = await self.refresh_ticker(ticker)
            report.results.append(result)
            logger.info(
                "reference_refresh ticker=%s status=%s calls=%s duration=%.2fs detail=%s",
                result.ticker,
                result.status,
                result.calls_used,
                result.duration_s,
                result.detail,
            )

            if result.status == STATUS_STOPPED:
                report.stopped_early = True
                report.stop_reason = result.detail
                break

        return report

    async def refresh_ticker(self, ticker: str) -> TickerResult:
        """Fetch, compute and upsert one ticker. Never raises for expected outcomes."""
        started = time.monotonic()
        ticker = ticker.strip().upper()

        if not self._force and await self._is_fresh_today(ticker):
            return TickerResult(
                ticker,
                STATUS_SKIPPED,
                detail="already refreshed today (use --force to override)",
                duration_s=time.monotonic() - started,
            )

        if self._dry_run:
            return TickerResult(
                ticker,
                STATUS_WOULD_REFRESH,
                detail=(
                    f"would use {self.calls_per_ticker} FMP call(s) "
                    + ("(eod/full; float from bulk lookup)" if self._float_lookup is not None
                       else "(eod/full + shares-float)")
                ),
                duration_s=time.monotonic() - started,
            )

        calls = 0
        try:
            # Bounded server-side: the deepest metric is SMA-200, so five years of
            # history is bandwidth we never read. See `reference_history_days`.
            #
            # NOT applied to fixture replay. Fixtures are keyed on the request params, and
            # `from` is a ROLLING date — a bounded key would change every day, so a
            # recorded fixture would go stale overnight rather than at some sensible point.
            # Replay therefore uses the unbounded shape, which is also the honest one:
            # bandwidth is not a property being tested offline.
            since = (
                None
                if isinstance(self._client, FixtureFmpClient)
                else date.today() - timedelta(days=get_settings().reference_history_days)
            )
            bars = await self._client.get_eod_history(ticker, since=since)
            calls += 1
        except SymbolNotAvailable as exc:
            await self._mark_inaccessible(ticker, str(exc))
            return TickerResult(
                ticker,
                STATUS_UNAVAILABLE,
                calls_used=1,
                detail=str(exc),
                duration_s=time.monotonic() - started,
            )
        except BudgetExhausted as exc:
            return TickerResult(
                ticker, STATUS_STOPPED, detail=str(exc), duration_s=time.monotonic() - started
            )
        except FmpError as exc:
            # A 429 means the provider cap is gone — stop the whole run, don't grind on.
            return TickerResult(
                ticker,
                STATUS_STOPPED if isinstance(exc, RateLimited) else STATUS_FAILED,
                calls_used=1,
                detail=str(exc),
                duration_s=time.monotonic() - started,
            )

        metrics = compute_reference_metrics(bars)

        # Float is fetched second and tolerated as missing: plenty of symbols have no
        # float on FMP, and losing the EOD metrics over that would be a bad trade.
        shares: Any | None = None
        float_note = ""
        if self._float_lookup is not None:
            shares = self._float_lookup.get(ticker)
            if shares is None:
                float_note = "no float in bulk lookup"
        else:
            try:
                shares = await self._client.get_shares_float(ticker)
                calls += 1
            except BudgetExhausted as exc:
                float_note = f"float skipped: {exc}"
            except FmpError as exc:
                calls += 1
                float_note = f"float unavailable: {exc}"

        await self._upsert(ticker, metrics, shares)

        detail = f"bars={metrics.bars_used}"
        if not metrics.is_complete:
            detail += " (incomplete: short history)"
        if float_note:
            detail += f"; {float_note}"

        return TickerResult(
            ticker,
            STATUS_REFRESHED,
            calls_used=calls,
            detail=detail,
            duration_s=time.monotonic() - started,
        )

    # ------------------------------------------------------------------ persistence

    async def _is_fresh_today(self, ticker: str) -> bool:
        async with self._session_factory() as session:
            computed_at = await session.scalar(
                select(ReferenceData.computed_at).where(ReferenceData.ticker == ticker)
            )
        return computed_at is not None and computed_at.date() == utc_today()

    async def _ensure_universe_row(self, session: AsyncSession, ticker: str) -> Universe:
        row = await session.scalar(select(Universe).where(Universe.ticker == ticker))
        if row is None:
            row = Universe(ticker=ticker, is_active=True)
            session.add(row)
            await session.flush()
        return row

    async def _mark_inaccessible(self, ticker: str, note: str) -> None:
        async with self._session_factory() as session:
            row = await self._ensure_universe_row(session, ticker)
            row.is_accessible_free_tier = False
            row.probe_note = note[:500]
            row.last_probed_at = datetime.utcnow()
            await session.commit()

    async def _upsert(
        self, ticker: str, metrics: ReferenceMetrics, shares: Any | None
    ) -> None:
        async with self._session_factory() as session:
            universe_row = await self._ensure_universe_row(session, ticker)
            universe_row.last_refreshed_at = datetime.utcnow()
            # The refresh succeeding is itself proof of accessibility.
            universe_row.is_accessible_free_tier = True

            row = await session.scalar(
                select(ReferenceData).where(ReferenceData.ticker == ticker)
            )
            if row is None:
                row = ReferenceData(ticker=ticker)
                session.add(row)

            # `floatShares` is a share count; `freeFloat` is a percentage of outstanding,
            # so only the former can populate static_float. Missing stays missing.
            row.static_float = (
                int(shares.float_shares)
                if shares is not None and shares.float_shares is not None
                else None
            )
            row.outstanding_shares = (
                int(shares.outstanding_shares)
                if shares is not None and shares.outstanding_shares is not None
                else None
            )
            row.volume_avg_20d = metrics.volume_avg_20d
            row.price_close_yesterday = metrics.price_close_yesterday
            row.high_yesterday = metrics.high_yesterday
            row.high_20d = metrics.high_20d
            row.sma_50 = metrics.sma_50
            row.sma_200 = metrics.sma_200
            row.last_bar_date = metrics.last_bar_date
            row.bars_used = metrics.bars_used
            row.data_source = "fixture" if isinstance(self._client, FixtureFmpClient) else "fmp"
            row.computed_at = datetime.utcnow()

            await session.commit()
