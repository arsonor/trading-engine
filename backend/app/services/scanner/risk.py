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

from app.services.scanner.candidate import STAGE_RISK, Candidate, Rejection, StageOutcome
from app.services.scanner.profiles import ThresholdProfile

logger = logging.getLogger(__name__)

TAPE_NEUTRAL = "neutral"
TAPE_RISK_ON = "risk_on"
TAPE_RISK_OFF = "risk_off"


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
        signal into a hard veto is a decision that should be made with data (Phase 6
        backtesting), not assumed here.
        """
        return False


@runtime_checkable
class MarketTapeProvider(Protocol):
    """Supplies market-wide condition context."""

    async def get_tape(self, as_of: datetime) -> MarketTape:
        ...


class NeutralMarketTape:
    """V1 stub: always neutral, and honest that it is not measuring anything.

    A tape check needs index futures or a broad-market proxy, which the FMP free tier does
    not serve. Returning `is_available=False` means downstream code can show "not
    measured" rather than a green light nobody earned.
    """

    async def get_tape(self, as_of: datetime) -> MarketTape:
        return MarketTape(
            state=TAPE_NEUTRAL,
            detail=(
                "Market-wide tape check not implemented in V1 — needs an index/futures "
                "feed (app V2). Treated as neutral; not a confirmation."
            ),
            is_available=False,
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

        outcome.survivors.append(candidate)

    return outcome
