"""EOD-derived reference metrics.

Pure functions over a list of daily bars — no I/O, no clock, no database. Everything the
morning scan needs from history is computed here once per night so the scan itself stays
inside the FMP rate limit.

Convention: bars arrive newest-first (FMP's order). "Yesterday" means the most recent
bar in the series, not a calendar computation — on a Monday pre-market that is Friday,
and on a holiday-shortened week it is whatever actually traded.
"""

from dataclasses import dataclass
from datetime import date

from app.services.fmp.models import EodBar

VOLUME_AVG_WINDOW = 20
HIGH_WINDOW = 20
SMA_SHORT_WINDOW = 50
SMA_LONG_WINDOW = 200


@dataclass(frozen=True)
class ReferenceMetrics:
    """Everything Stage 1 and Stage 3 need, derived from one EOD history call."""

    volume_avg_20d: float | None
    price_close_yesterday: float | None
    high_yesterday: float | None
    high_20d: float | None
    sma_50: float | None
    sma_200: float | None
    last_bar_date: date | None
    bars_used: int

    @property
    def is_complete(self) -> bool:
        """True when every metric the scanner uses is present.

        SMA-50/200 are allowed to be missing for recently listed tickers; the scanner
        treats a missing SMA as "no resistance level from that source", not as zero.
        """
        return None not in (
            self.volume_avg_20d,
            self.price_close_yesterday,
            self.high_yesterday,
            self.high_20d,
        )


def _sorted_desc(bars: list[EodBar]) -> list[EodBar]:
    return sorted(bars, key=lambda b: b.date, reverse=True)


def _mean(values: list[float]) -> float:
    return sum(values) / len(values)


def _window_mean(values: list[float], window: int) -> float | None:
    """Mean of the most recent `window` values, or None if history is too short.

    Returning None rather than averaging what exists is deliberate: a "200-day SMA"
    computed from 40 bars is a different statistic wearing the same name.
    """
    if len(values) < window:
        return None
    return _mean(values[:window])


def compute_reference_metrics(bars: list[EodBar]) -> ReferenceMetrics:
    """Derive the reference metrics from a daily-bar history."""
    if not bars:
        return ReferenceMetrics(None, None, None, None, None, None, None, 0)

    ordered = _sorted_desc(bars)
    closes = [b.close for b in ordered]
    highs = [b.high for b in ordered]
    volumes = [b.volume for b in ordered]
    latest = ordered[0]

    return ReferenceMetrics(
        volume_avg_20d=_window_mean(volumes, VOLUME_AVG_WINDOW),
        price_close_yesterday=latest.close,
        high_yesterday=latest.high,
        high_20d=max(highs[:HIGH_WINDOW]) if len(highs) >= HIGH_WINDOW else None,
        sma_50=_window_mean(closes, SMA_SHORT_WINDOW),
        sma_200=_window_mean(closes, SMA_LONG_WINDOW),
        last_bar_date=latest.date,
        bars_used=len(ordered),
    )
