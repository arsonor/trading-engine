"""Empirical discovery of which symbols the FMP key can actually serve.

FMP documents the free tier as "a sample of ~87 symbols" without publishing the list, and
the list has moved before. Designing the V1 universe around a documented assumption would
mean discovering the mismatch in production, so the universe is probed instead: whatever
answers is the universe.

`batch-quote` would do this for one call per chunk, but it is **402-restricted on the
free tier** (verified July 2026) — as are `stock-list` and `company-screener`. So the
probe tries batch first and falls back to one `quote` call per symbol, which is what the
free tier actually supports: a restricted ticker answers 402 "Special Endpoint: this
value set for 'symbol' is not available", an accessible one answers 200.

The batch path is kept because it costs one call instead of ~90, and it starts working
the moment the key is upgraded to Starter — no code change needed.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.universe import Universe
from app.services.fmp.client import FmpClient
from app.services.fmp.errors import AuthFailed, BudgetExhausted, FmpError, SymbolNotAvailable

logger = logging.getLogger(__name__)

# Symbols to test. Large caps are the documented free-tier sample; the control group at
# the end is there to confirm the probe can detect a NEGATIVE — a probe that says "yes"
# to everything is telling you nothing.
DEFAULT_CANDIDATES: list[str] = [
    # Mega/large caps (expected accessible)
    "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "BRK-B", "AVGO",
    "JPM", "V", "MA", "UNH", "XOM", "JNJ", "WMT", "PG", "HD", "COST",
    "ORCL", "CVX", "ABBV", "KO", "PEP", "MRK", "BAC", "CRM", "AMD", "ADBE",
    "NFLX", "TMO", "LLY", "ACN", "MCD", "CSCO", "ABT", "DHR", "INTC", "VZ",
    "TXN", "QCOM", "NKE", "PM", "DIS", "WFC", "CAT", "AMGN", "IBM", "GE",
    "NOW", "UBER", "BA", "SBUX", "GS", "BLK", "MS", "RTX", "HON", "UNP",
    "LOW", "SPGI", "T", "PFE", "COP", "AXP", "BKNG", "DE", "LMT", "SYK",
    "PLD", "MDT", "ADP", "TJX", "CVS", "MU", "GILD", "C", "MDLZ", "SCHW",
    "MMM", "F", "GM", "PYPL", "SHOP", "SQ", "PLTR",
    # Control group: small/micro caps that SHOULD be inaccessible on the free tier.
    # If these come back accessible, the free-tier restriction is not what we think.
    "SNDL", "GNS", "MULN", "BBIG", "ATER",
]

# batch-quote takes a comma-separated list; keep chunks small enough to stay well inside
# any URL-length limit while still spending only a few calls overall.
PROBE_CHUNK_SIZE = 25

# Symbols after this point in DEFAULT_CANDIDATES are the negative control group.
CONTROL_GROUP = {"SNDL", "GNS", "MULN", "BBIG", "ATER"}


MODE_BATCH = "batch-quote"
MODE_PER_SYMBOL = "quote (per symbol)"


@dataclass
class ProbeReport:
    """What the probe found."""

    accessible: list[str] = field(default_factory=list)
    inaccessible: list[str] = field(default_factory=list)
    calls_used: int = 0
    stopped_early: bool = False
    stop_reason: str = ""
    mode: str = MODE_BATCH
    names: dict[str, str] = field(default_factory=dict)
    exchanges: dict[str, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def control_accessible(self) -> list[str]:
        """Control-group symbols that unexpectedly answered."""
        return [s for s in self.accessible if s in CONTROL_GROUP]

    @property
    def universe_size(self) -> int:
        return len(self.accessible)


def _chunk(items: list[str], size: int) -> list[list[str]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


class SymbolProber:
    """Probes candidate symbols and persists the result into `universe`."""

    def __init__(
        self,
        client: FmpClient,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        chunk_size: int = PROBE_CHUNK_SIZE,
    ) -> None:
        if session_factory is None:
            from app.core.database import async_session_maker

            session_factory = async_session_maker
        self._client = client
        self._session_factory = session_factory
        self._chunk_size = chunk_size

    async def probe(self, candidates: list[str] | None = None) -> ProbeReport:
        """Test each candidate and return the accessible set."""
        symbols = [s.strip().upper() for s in (candidates or DEFAULT_CANDIDATES) if s.strip()]
        report = ProbeReport()
        remaining = list(symbols)

        for chunk in _chunk(symbols, self._chunk_size):
            try:
                quotes = await self._client.get_batch_quotes(chunk)
                report.calls_used += 1
            except BudgetExhausted as exc:
                report.stopped_early = True
                report.stop_reason = str(exc)
                logger.warning("Probe stopped: %s", exc)
                break
            except AuthFailed as exc:
                # batch-quote is plan-restricted (the free tier's answer). Fall back to
                # one call per symbol rather than giving up on the universe.
                report.calls_used += 1
                report.mode = MODE_PER_SYMBOL
                report.notes.append(f"batch-quote unavailable on this plan ({exc}); fell back to per-symbol quotes")
                logger.warning("batch-quote unavailable, falling back to per-symbol probe: %s", exc)
                await self._probe_per_symbol(remaining, report)
                break
            except FmpError as exc:
                report.calls_used += 1
                report.stopped_early = True
                report.stop_reason = f"Probe aborted on chunk {chunk[0]}..{chunk[-1]}: {exc}"
                logger.error(report.stop_reason)
                break

            returned = {}
            for quote in quotes:
                # A row with no price is a placeholder, not real access.
                if quote.price is not None:
                    returned[quote.symbol.upper()] = quote

            for symbol in chunk:
                quote = returned.get(symbol)
                if quote is not None:
                    self._record_accessible(report, symbol, quote.name, quote.exchange)
                else:
                    report.inaccessible.append(symbol)
                remaining.remove(symbol)

        await self._persist(report)
        return report

    async def _probe_per_symbol(self, symbols: list[str], report: ProbeReport) -> None:
        """One `quote` call per symbol — the free tier's only working availability test."""
        for symbol in symbols:
            try:
                quote = await self._client.get_quote(symbol)
                report.calls_used += 1
                if quote.price is not None:
                    self._record_accessible(report, symbol, quote.name, quote.exchange)
                else:
                    report.inaccessible.append(symbol)
            except SymbolNotAvailable:
                report.calls_used += 1
                report.inaccessible.append(symbol)
            except BudgetExhausted as exc:
                report.stopped_early = True
                report.stop_reason = str(exc)
                logger.warning("Probe stopped: %s", exc)
                return
            except FmpError as exc:
                report.calls_used += 1
                report.stopped_early = True
                report.stop_reason = f"Probe aborted at {symbol}: {exc}"
                logger.error(report.stop_reason)
                return

    @staticmethod
    def _record_accessible(
        report: ProbeReport, symbol: str, name: str | None, exchange: str | None
    ) -> None:
        report.accessible.append(symbol)
        if name:
            report.names[symbol] = name
        if exchange:
            report.exchanges[symbol] = exchange

    async def _persist(self, report: ProbeReport) -> None:
        """Write probe results to `universe`. The accessible set IS the V1 universe."""
        now = datetime.utcnow()
        async with self._session_factory() as session:
            for symbol in report.accessible + report.inaccessible:
                row = await session.scalar(select(Universe).where(Universe.ticker == symbol))
                if row is None:
                    row = Universe(ticker=symbol)
                    session.add(row)

                accessible = symbol in report.accessible
                row.is_accessible_free_tier = accessible
                row.last_probed_at = now
                row.probe_note = (
                    "batch-quote returned a price"
                    if accessible
                    else "absent from batch-quote response (not served on this plan)"
                )
                if accessible:
                    # Only accessible symbols are active: an inactive row keeps the
                    # negative result on record instead of silently dropping it.
                    row.is_active = True
                    if report.names.get(symbol):
                        row.name = report.names[symbol][:255]
                    if report.exchanges.get(symbol):
                        row.exchange = report.exchanges[symbol][:50]
                else:
                    row.is_active = False

            await session.commit()

    async def accessible_universe(self) -> list[str]:
        """Currently known accessible universe, from the DB."""
        async with self._session_factory() as session:
            result = await session.execute(
                select(Universe.ticker)
                .where(Universe.is_accessible_free_tier.is_(True), Universe.is_active.is_(True))
                .order_by(Universe.ticker)
            )
            return list(result.scalars().all())
