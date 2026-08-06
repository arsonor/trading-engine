"""Two-step universe build: screener pre-filter, then the exact float cap applied locally.

## Why two steps

`company-screener` cannot see float — Phase 4A confirmed its 15 fields include market cap,
price, volume, sector and exchange, but nothing about shares available to trade. Float is
the *first* Stage-1 filter, so it has to come from `shares-float-all` and be joined locally.

The order matters. The screener runs first because it is one call that narrows ~19,500 US
symbols to ~1,900, and the float lookup is 8 calls for the entire market regardless. Doing
it the other way round (float first) would mean 11,504 US symbols under the float cap with
no liquidity filter, most of them untradeable.

## Err toward inclusion in step 1

**Anything the screener wrongly excludes is never seen again by any later stage.** There is
no recovery path: a ticker missing from the pre-filter simply does not exist as far as the
scanner is concerned, whatever its float turns out to be. So the pre-filter is deliberately
loose — price and volume only, from config — and the exact `float < 75M` cap is applied
afterwards against `reference_data`, where it can be tightened or relaxed without losing
candidates permanently.

## Delisting

Symbols that disappear from the screener are marked inactive, never deleted. Alert history
points at tickers by symbol, and a delisted name still has to render on the dashboard for
whatever alerts it produced while it was alive.
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.models.universe import Universe
from app.models.universe_run import UniverseRun, UniverseRunStatus
from app.services.fmp.client import FmpClient

logger = logging.getLogger(__name__)

# US listings the scanner will consider. OTC is excluded deliberately: the strategy needs
# a tradeable, quotable name, and OTC pre-market data is thin to nonexistent.
US_EXCHANGES = {"NASDAQ", "NYSE", "AMEX", "NYSE MKT", "NYSEAMERICAN", "BATS", "CBOE"}


@dataclass
class UniverseReport:
    """What one build did — mirrors `universe_runs` and drives the CLI output."""

    screener_count: int = 0
    float_rows: int = 0
    universe_size: int = 0
    activated: int = 0
    deactivated: int = 0
    unchanged: int = 0
    without_float: int = 0
    stage1_eligible: int | None = None
    calls_used: int = 0
    bytes_used: int = 0
    warning: str | None = None
    tickers: list[str] = field(default_factory=list)
    run_id: int | None = None

    @property
    def dropped_by_float_cap(self) -> int:
        return max(0, self.screener_count - self.universe_size - self.without_float)


class UniverseBuilder:
    """Builds the Stage-1 universe from live Premium data."""

    def __init__(
        self,
        client: FmpClient | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        if session_factory is None:
            from app.core.database import async_session_maker

            session_factory = async_session_maker
        self._session_factory = session_factory
        self._client = client
        self._settings = get_settings()

    # ------------------------------------------------------------------ step 1

    async def screen(self, client: FmpClient) -> list[dict[str, Any]]:
        """The over-inclusive pre-filter. Values come from config, never literals.

        **`volumeMoreThan` is deliberately NOT used, and that is a measured decision.**
        The screener's `volume` field is *today's session volume so far*, not a 20-day
        average. Measured on 6 August 2026 with an identical request:

            04:22 ET (pre-market)   1,880 rows   <- field holds the PREVIOUS session
            09:33 ET (3 min after open)  159 rows   <- field holds 3 minutes of trading

        Filtering on it would make the universe depend on what time the nightly job
        happened to run, and would exclude names on the wrong metric entirely: Stage 1
        wants `volume_avg_20d`, which is a different quantity. Since anything the screener
        drops is never seen again by any later stage, that exclusion would be permanent
        and invisible.

        So liquidity is filtered **locally**, in Stage 1, against `reference_data.volume_avg_20d`
        — where it is the right number, computed from EOD history, and where loosening the
        threshold re-admits names instead of requiring a fresh universe build.

        Price is filtered here, but with a margin: the screener reports a live price, while
        the scanner compares against the prior close. A name sitting just under the floor
        today can gap through it tomorrow morning, and without the margin it would be
        absent from the universe for the whole session.
        """
        s = self._settings
        floor = s.scan_price_floor * (1 - s.universe_price_margin_pct / 100.0)
        rows = await client.screen(
            priceMoreThan=round(floor, 4),
            isEtf="false",
            isFund="false",
            isActivelyTrading="true",
            country="US",
            limit=10_000,
        )
        kept = [
            r for r in rows
            if str(r.get("symbol", "")).strip()
            and (r.get("exchangeShortName") or "").upper() in US_EXCHANGES
        ]
        logger.info(
            "Screener pre-filter: %s rows, %s on US exchanges (price > %.2f = floor %.2f "
            "less a %.0f%% inclusion margin; volume filtered later against volume_avg_20d)",
            len(rows), len(kept), floor, s.scan_price_floor, s.universe_price_margin_pct,
        )
        return kept

    # ------------------------------------------------------------------ step 2

    async def bulk_floats(self, client: FmpClient, max_pages: int = 12) -> dict[str, float]:
        """Float for the whole market: ~8 calls, not one per ticker.

        Stops on the first short page — FMP signals the end by returning fewer than the
        page size rather than an empty page, so requesting a fixed 8 would either miss
        rows as the market grows or waste a call.
        """
        floats: dict[str, float] = {}
        for page in range(max_pages):
            rows = await client.get_shares_float_page(page=page)
            if not rows:
                break
            for row in rows:
                if row.float_shares and row.float_shares > 0:
                    floats[row.symbol.upper()] = float(row.float_shares)
            if len(rows) < 5000:
                break
        logger.info("Bulk float: %s symbols with a usable float", len(floats))
        return floats

    # ------------------------------------------------------------------ persistence

    async def _apply(
        self, session: AsyncSession, rows: list[dict[str, Any]], floats: dict[str, float]
    ) -> UniverseReport:
        """Join screener output to float, apply the exact cap, and upsert.

        The float cap is applied HERE rather than in the screener request, so that
        loosening it later re-admits names instead of requiring a wider pre-filter.
        """
        report = UniverseReport(screener_count=len(rows), float_rows=len(floats))
        # The WIDEST cap any profile could ask for, not the production one.
        #
        # `universe` is the set we maintain reference_data for; `float < 75M` is a
        # *threshold*, and thresholds are per-profile and user-editable. Baking the
        # production value in here had two bad effects: it deactivated every megacap, which
        # silently broke the demo profile (whose whole purpose is a loosened float cap), and
        # it meant raising the threshold in the dashboard would do nothing until someone
        # remembered to rebuild the universe.
        #
        # Stage 1 applies the profile's actual cap in SQL against reference_data, where
        # loosening it re-admits names immediately.
        cap = max(self._settings.scan_float_max, self._settings.scan_demo_float_max)

        keep: dict[str, dict[str, Any]] = {}
        for row in rows:
            ticker = str(row["symbol"]).strip().upper()
            shares = floats.get(ticker)
            if shares is None:
                report.without_float += 1
                continue
            if shares < cap:
                keep[ticker] = row

        existing = {
            u.ticker: u
            for u in (await session.execute(select(Universe))).scalars().all()
        }
        now = datetime.utcnow()

        for ticker, row in keep.items():
            current = existing.get(ticker)
            if current is None:
                session.add(Universe(
                    ticker=ticker,
                    name=(row.get("companyName") or None),
                    exchange=(row.get("exchangeShortName") or None),
                    is_active=True,
                    updated_at=now,
                ))
                report.activated += 1
            else:
                if not current.is_active:
                    report.activated += 1
                else:
                    report.unchanged += 1
                current.is_active = True
                current.name = row.get("companyName") or current.name
                current.exchange = row.get("exchangeShortName") or current.exchange
                current.updated_at = now

        # Deactivate, never delete: alert history points at these tickers by symbol.
        vanished = [t for t, u in existing.items() if u.is_active and t not in keep]
        if vanished:
            await session.execute(
                update(Universe)
                .where(Universe.ticker.in_(vanished))
                .values(is_active=False, updated_at=now)
            )
            report.deactivated = len(vanished)

        report.universe_size = len(keep)
        report.tickers = sorted(keep)
        return report

    # ------------------------------------------------------------------ size watch

    async def _trailing_median(self, session: AsyncSession, limit: int = 10) -> int | None:
        sizes = (await session.execute(
            select(UniverseRun.universe_size)
            .where(UniverseRun.universe_size.isnot(None),
                   UniverseRun.status == UniverseRunStatus.COMPLETED)
            .order_by(UniverseRun.started_at.desc())
            .limit(limit)
        )).scalars().all()
        return int(statistics.median(sizes)) if sizes else None

    async def _stage1_eligible(self, session: AsyncSession) -> int | None:
        """How many active tickers currently clear the PRODUCTION Stage-1 filters.

        This is the set the live scan walks on every 5-minute pass, so it — not the
        maintained universe — is what 4A's bandwidth ceiling describes. Computed from
        existing `reference_data`, so it reflects last night's metrics; None before the
        first refresh, when there is nothing to count.
        """
        from app.models.reference_data import ReferenceData

        s = self._settings
        total = await session.scalar(
            select(func.count()).select_from(ReferenceData)
        )
        if not total:
            return None
        return await session.scalar(
            select(func.count())
            .select_from(ReferenceData)
            .join(Universe, Universe.ticker == ReferenceData.ticker)
            .where(
                Universe.is_active.is_(True),
                ReferenceData.static_float.isnot(None),
                ReferenceData.static_float < s.scan_float_max,
                ReferenceData.volume_avg_20d.isnot(None),
                ReferenceData.volume_avg_20d > s.scan_avg_volume_min,
            )
        )

    def _size_warning(
        self, size: int, median: int | None, stage1: int | None
    ) -> str | None:
        """Flag a surprising universe. A warning, never a failure.

        A universe that moved is a thing to look at, not a reason to leave the scanner
        without data — the build still commits.

        The ceiling is checked against the **Stage-1 eligible** count rather than the
        maintained universe. 4A's ~3,500 figure is about per-pass bandwidth and the
        5-minute cadence, which only the scanned set consumes; the maintained set costs one
        EOD call each per night and is expected to be several times larger. Checking the
        ceiling against the wrong number would warn every single night and train the
        operator to ignore it.
        """
        s = self._settings
        if stage1 is not None and stage1 > s.universe_size_ceiling:
            return (
                f"{stage1:,} tickers now clear Stage 1, above the configured ceiling of "
                f"{s.universe_size_ceiling:,}. Phase 4A projected bandwidth pressure past "
                f"roughly 3,500, and each pass must still finish inside the 5-minute "
                f"cadence. Check whether a threshold was edited."
            )
        if median is None:
            return None
        move = abs(size - median) / median * 100 if median else 0.0
        if move >= s.universe_size_move_pct:
            direction = "grew" if size > median else "shrank"
            return (
                f"Universe {direction} {move:.0f}% versus its trailing median of "
                f"{median:,} ({median:,} -> {size:,}). Thresholds move this immediately, so "
                f"check for a settings edit before assuming the market moved."
            )
        return None

    # ------------------------------------------------------------------ entry point

    async def build(self) -> UniverseReport:
        """Run the whole build and record it. Returns the report."""
        owns = self._client is None
        client = self._client or FmpClient()
        started = datetime.utcnow()
        calls_before = await client.budget.calls_used_today()
        bytes_before = await client.budget.bytes_used_today()

        async with self._session_factory() as session:
            run = UniverseRun(started_at=started, status=UniverseRunStatus.RUNNING)
            session.add(run)
            await session.commit()
            await session.refresh(run)
            run_id = run.id

        try:
            rows = await self.screen(client)
            floats = await self.bulk_floats(client)
            async with self._session_factory() as session:
                report = await self._apply(session, rows, floats)
                await session.flush()
                report.stage1_eligible = await self._stage1_eligible(session)
                median = await self._trailing_median(session)
                report.warning = self._size_warning(
                    report.universe_size, median, report.stage1_eligible
                )
                await session.commit()
        except Exception as exc:
            async with self._session_factory() as session:
                await session.execute(
                    update(UniverseRun).where(UniverseRun.id == run_id).values(
                        status=UniverseRunStatus.FAILED,
                        finished_at=datetime.utcnow(),
                        error=f"{type(exc).__name__}: {exc}"[:2000],
                    )
                )
                await session.commit()
            raise
        finally:
            if owns:
                await client.aclose()

        report.run_id = run_id
        report.calls_used = await client.budget.calls_used_today() - calls_before
        report.bytes_used = await client.budget.bytes_used_today() - bytes_before

        async with self._session_factory() as session:
            await session.execute(
                update(UniverseRun).where(UniverseRun.id == run_id).values(
                    status=UniverseRunStatus.COMPLETED,
                    finished_at=datetime.utcnow(),
                    screener_count=report.screener_count,
                    float_rows=report.float_rows,
                    universe_size=report.universe_size,
                    stage1_eligible=report.stage1_eligible,
                    activated=report.activated,
                    deactivated=report.deactivated,
                    calls_used=report.calls_used,
                    bytes_used=report.bytes_used,
                    warning=report.warning,
                )
            )
            await session.commit()

        if report.warning:
            logger.warning("Universe size check: %s", report.warning)
        return report
