"""The candidate record that flows through the three stages.

One mutable object per ticker, enriched as it survives each stage. Rejections are kept
rather than discarded: "nothing passed Stage 2" is only actionable if you can see *why*
each ticker died, and that reasoning is what the Phase 3 scan-status panel shows.
"""

from dataclasses import dataclass, field
from datetime import datetime

# Stage identifiers, used in rejection records and stage counts.
STAGE_1 = "stage_1_liquidity"
STAGE_2 = "stage_2_momentum"
STAGE_3 = "stage_3_room_to_run"
STAGE_RISK = "risk_filters"


@dataclass
class Candidate:
    """A ticker under evaluation, carrying every value the stages compute."""

    ticker: str

    # --- Stage 1 inputs, from `reference_data` (real EOD data even in V1) ---
    static_float: int | None = None
    volume_avg_20d: float | None = None
    price_close_yesterday: float | None = None
    high_yesterday: float | None = None
    high_20d: float | None = None
    sma_50: float | None = None
    sma_200: float | None = None
    reference_computed_at: datetime | None = None
    reference_source: str = "fmp"

    # --- Stage 2, from the market snapshot ---
    price_premarket_current: float | None = None
    volume_premarket_accumulated: float | None = None
    snapshot_source: str | None = None
    gap_pct: float | None = None
    rvol_pct: float | None = None
    rvol_mode: str | None = None
    rvol_is_approximate: bool = False
    rvol_detail: str = ""

    # --- Stage 3 ---
    nearest_resistance: float | None = None
    resistance_source: str | None = None
    upside_pct: float | None = None

    def resistance_levels(self) -> dict[str, float]:
        """Named resistance levels that exist for this ticker."""
        levels = {
            "high_yesterday": self.high_yesterday,
            "high_20d": self.high_20d,
            "sma_50": self.sma_50,
            "sma_200": self.sma_200,
        }
        return {name: value for name, value in levels.items() if value is not None}

    def dollar_volume(self) -> float | None:
        """Average daily dollar volume — the tradeable-size proxy for the risk filter."""
        if self.volume_avg_20d is None or self.price_close_yesterday is None:
            return None
        return self.volume_avg_20d * self.price_close_yesterday

    def as_dict(self) -> dict:
        """Flat payload for logs and the Phase 3 alert contract."""
        return {
            "ticker": self.ticker,
            "gap_pct": self.gap_pct,
            "rvol_pct": self.rvol_pct,
            "rvol_mode": self.rvol_mode,
            "rvol_is_approximate": self.rvol_is_approximate,
            "entry_reference_price": self.price_premarket_current,
            "nearest_resistance": self.nearest_resistance,
            "resistance_source": self.resistance_source,
            "upside_pct": self.upside_pct,
            "static_float": self.static_float,
            "volume_avg_20d": self.volume_avg_20d,
            "price_close_yesterday": self.price_close_yesterday,
            "snapshot_source": self.snapshot_source,
        }


@dataclass(frozen=True)
class Rejection:
    """Why one ticker stopped advancing."""

    ticker: str
    stage: str
    reason: str
    detail: str = ""

    def __str__(self) -> str:
        return f"{self.ticker} rejected at {self.stage}: {self.reason}"


@dataclass
class StageOutcome:
    """Survivors and rejections from one stage."""

    survivors: list[Candidate] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
