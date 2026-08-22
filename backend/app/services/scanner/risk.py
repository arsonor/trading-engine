"""Risk filters — blocks that override the three stages.

These run against the LIVE pre-market price, which is why they are not folded into
Stage 1's SQL. Stage 1 screens on yesterday's close; a stock can clear a $2 floor on
yesterday's close and still be trading at $1.80 pre-market. The filter that protects the
user has to look at the price they would actually pay.

Per `docs/CLAUDE.md` section 4.3, a risk filter blocks the alert regardless of how well
the ticker scored — it is a veto, not a factor.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from app.config import get_settings
from app.services.scanner.candidate import STAGE_RISK, Candidate, Rejection, StageOutcome
from app.services.scanner.profiles import ThresholdProfile

logger = logging.getLogger(__name__)

TAPE_NEUTRAL = "neutral"
TAPE_RISK_ON = "risk_on"
TAPE_RISK_OFF = "risk_off"

# Data-quality rejection reasons. Named and distinct from ordinary stage rejections so
# "3 candidates suppressed for implausible reference data" is reportable information
# rather than a silent drop.
REASON_IMPLAUSIBLE_UPSIDE = "implausible upside"
REASON_PRICE_REGIME_BREAK = "price regime break"
DATA_QUALITY_REASONS = frozenset({REASON_IMPLAUSIBLE_UPSIDE, REASON_PRICE_REGIME_BREAK})


@dataclass(frozen=True)
class MarketTape:
    """Market-wide context. A red tape lowers confidence in every long setup."""

    state: str
    detail: str
    is_available: bool = True

    @property
    def blocks_alerts(self) -> bool:
        """Whether the tape is bad enough to veto alerts outright.

        Currently never true. The spec calls for tape *context*, and turning a market
        signal into a hard veto is a decision that should be made with data (Phase 5
        backtesting), not assumed here.
        """
        return False


@runtime_checkable
class MarketTapeProvider(Protocol):
    """Supplies market-wide condition context."""

    async def get_tape(self, as_of: datetime) -> MarketTape:
        ...


class NeutralMarketTape:
    """Always neutral, and honest that it is not measuring anything.

    Kept as the fallback and the offline/test default. `is_available=False` means
    downstream code shows "not measured" rather than a green light nobody earned.
    """

    async def get_tape(self, as_of: datetime) -> MarketTape:
        return MarketTape(
            state=TAPE_NEUTRAL,
            detail=(
                "Market-wide tape check not performed. Treated as neutral; not a "
                "confirmation."
            ),
            is_available=False,
        )


class FmpMarketTape:
    """Broad-market context from a pre-market index proxy (default SPY).

    **Never allowed to abort a scan.** The tape is a confidence input and a risk filter,
    not a gate — `docs/CLAUDE.md` §4.3 — so an unreachable index degrades to
    `is_available=False` and the morning proceeds. Letting one extra HTTP call decide
    whether 694 tickers get scanned would be a poor trade.

    Read from the same `extended=true` bars the scanner already uses, rather than a quote:
    Phase 4A measured that quote endpoints serve the *previous* session's close during
    pre-market, which would make the tape a reading of yesterday dressed as today.
    """

    def __init__(self, client: object | None = None, symbol: str | None = None) -> None:
        self._client = client
        self._owns_client = client is None
        self._symbol = symbol or "SPY"

    async def get_tape(self, as_of: datetime) -> MarketTape:
        from zoneinfo import ZoneInfo

        from app.config import get_settings
        from app.services.bars import Bar, premarket_bars, settled_bars
        from app.services.fmp.client import FmpClient

        tz = ZoneInfo(get_settings().scanner_timezone)
        client = self._client or FmpClient()
        try:
            session_date = as_of.astimezone(tz).date()
            rows = await client.get_intraday_bars(
                self._symbol, interval="5min",
                start=session_date, end=session_date, extended=True,
            )
        except Exception as exc:  # noqa: BLE001 - the tape must never fail a scan
            logger.warning("Market tape unavailable (%s): %s", self._symbol, exc)
            return MarketTape(
                state=TAPE_NEUTRAL,
                detail=f"{self._symbol} could not be read ({type(exc).__name__}); "
                       f"tape not measured. The scan continues.",
                is_available=False,
            )
        finally:
            if self._owns_client:
                await client.aclose()

        bars = [
            Bar(start=r.date.replace(tzinfo=tz), volume=r.volume, close=r.close)
            for r in rows
        ]
        window = [b for b in premarket_bars(bars) if b.start <= as_of]
        settled = settled_bars(window, now=as_of)
        if not settled:
            return MarketTape(
                state=TAPE_NEUTRAL,
                detail=f"{self._symbol} has no settled pre-market bars yet at "
                       f"{as_of:%H:%M} ET; tape not measured.",
                is_available=False,
            )

        first, last = settled[0], settled[-1]
        if not first.close or not last.close:
            return MarketTape(
                state=TAPE_NEUTRAL,
                detail=f"{self._symbol} bars carry no close price; tape not measured.",
                is_available=False,
            )

        change_pct = (last.close - first.close) / first.close * 100
        state = (
            TAPE_RISK_OFF if change_pct <= -0.5
            else TAPE_RISK_ON if change_pct >= 0.5
            else TAPE_NEUTRAL
        )
        return MarketTape(
            state=state,
            detail=(
                f"{self._symbol} {change_pct:+.2f}% across {len(settled)} settled "
                f"pre-market bar(s) to {last.end:%H:%M} ET."
            ),
            is_available=True,
        )


def apply_risk_filters(
    candidates: list[Candidate], profile: ThresholdProfile, tape: MarketTape
) -> StageOutcome:
    """Veto candidates that fail a hard safety check."""
    outcome = StageOutcome()

    for candidate in candidates:
        price = candidate.price_premarket_current
        if price is None:
            outcome.rejections.append(
                Rejection(candidate.ticker, STAGE_RISK, "no price", "cannot apply risk filters")
            )
            continue

        # Sub-floor names hit 5% on noise, so the move means nothing.
        if price < profile.price_floor:
            outcome.rejections.append(
                Rejection(
                    candidate.ticker,
                    STAGE_RISK,
                    "below price floor",
                    f"pre-market price {price:.2f} < {profile.price_floor}",
                )
            )
            continue

        dollar_volume = candidate.dollar_volume()
        if dollar_volume is None:
            outcome.rejections.append(
                Rejection(
                    candidate.ticker,
                    STAGE_RISK,
                    "no dollar volume",
                    "missing volume_avg_20d or prior close",
                )
            )
            continue

        if dollar_volume < profile.dollar_volume_min:
            outcome.rejections.append(
                Rejection(
                    candidate.ticker,
                    STAGE_RISK,
                    "insufficient dollar volume",
                    f"${dollar_volume:,.0f} < ${profile.dollar_volume_min:,.0f} — "
                    f"too thin to trade in size",
                )
            )
            continue

        if tape.blocks_alerts:
            outcome.rejections.append(
                Rejection(candidate.ticker, STAGE_RISK, "market tape", tape.detail)
            )
            continue

        quality = _reject_implausible_reference(candidate)
        if quality is not None:
            outcome.rejections.append(quality)
            continue

        outcome.survivors.append(candidate)

    return outcome


def _reject_implausible_reference(candidate: Candidate) -> Rejection | None:
    """Veto a candidate whose resistance levels describe a price regime it has left.

    **Why this is a rejection rather than a flag.** Phase 4C recorded these as integrity
    findings and let the candidate through. That is the wrong shape for this particular
    problem: `upside_pct` is the sort key for the candidate list, so a ticker with a
    fabricated-looking 540% upside does not appear somewhere in the middle where a warning
    might be read — it appears **first**. The end user's opening impression of the product
    would be its least defensible row.

    **Why it is a risk filter and not stage arithmetic.** `docs/CLAUDE.md` §4.3 provides
    for risk filters that block an alert regardless of the stage outcome. Stage 3 still
    computes upside exactly as before; this only decides whether the result is fit to show.
    Nothing here touches how a candidate is scored or ranked.

    **Why it stays even though the data turned out to be correct.** The 4C hypothesis was
    that FMP served unadjusted history; measurement disproved that (see
    `app/services/scanner/integrity.py`). These are real collapses. But a real collapse
    produces an upside figure with no thesis behind it just as reliably as bad data would,
    and the next cause — genuinely stale data, a bad split feed, a corporate action nobody
    anticipated — will produce the same shape. The filter catches the shape.
    """
    settings = get_settings()

    upside = candidate.upside_pct
    if upside is not None and upside > settings.scan_upside_max:
        return Rejection(
            candidate.ticker,
            STAGE_RISK,
            REASON_IMPLAUSIBLE_UPSIDE,
            f"upside {upside:.1f}% exceeds the {settings.scan_upside_max:g}% ceiling. "
            f"Nearest resistance {candidate.nearest_resistance} "
            f"({candidate.resistance_source}) is far above the current price, so this is a "
            f"number without a thesis rather than a better opportunity.",
        )

    close = candidate.price_close_yesterday
    high = candidate.high_20d
    if close and high and close > 0:
        ratio = high / close
        if ratio > settings.scan_price_regime_break_ratio:
            return Rejection(
                candidate.ticker,
                STAGE_RISK,
                REASON_PRICE_REGIME_BREAK,
                f"20-day high {high:,.2f} is {ratio:.1f}x the prior close {close:,.2f} "
                f"(ceiling {settings.scan_price_regime_break_ratio:g}x). The stock has left "
                f"the price regime its resistance levels describe.",
            )

    return None
