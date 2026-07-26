"""Golden-value tests for the EOD-derived reference metrics.

These numbers feed Stage 1 (float + average volume) and Stage 3 (resistance levels), so
an off-by-one in a window silently shifts every candidate the scanner produces.
"""

from datetime import date, timedelta

from app.services.fmp.models import EodBar
from app.services.reference.metrics import compute_reference_metrics

LATEST = date(2026, 7, 24)


def make_bars(count: int, *, close_start: float = 100.0, volume: float = 1_000_000) -> list[EodBar]:
    """`count` daily bars, oldest first: close rises by 0.5/day, high is close + 1."""
    bars = []
    for i in range(count):
        close = close_start + i * 0.5
        bars.append(
            EodBar(
                date=LATEST - timedelta(days=count - 1 - i),
                open=close - 0.25,
                high=close + 1.0,
                low=close - 1.0,
                close=close,
                volume=volume,
            )
        )
    return bars


def test_full_history_produces_every_metric():
    metrics = compute_reference_metrics(make_bars(260))

    assert metrics.last_bar_date == LATEST
    assert metrics.bars_used == 260
    assert metrics.price_close_yesterday == 100.0 + 259 * 0.5  # 229.5
    assert metrics.high_yesterday == 230.5
    assert metrics.high_20d == 230.5
    assert metrics.volume_avg_20d == 1_000_000
    # Mean of the newest 50 closes: indices 210..259.
    assert metrics.sma_50 == 217.25
    # Mean of the newest 200 closes: indices 60..259.
    assert metrics.sma_200 == 179.75
    assert metrics.is_complete


def test_bars_may_arrive_in_any_order():
    ascending = make_bars(60)
    descending = list(reversed(ascending))

    assert compute_reference_metrics(ascending) == compute_reference_metrics(descending)


def test_short_history_leaves_long_windows_none():
    """A '200-day SMA' from 60 bars is a different statistic wearing the same name."""
    metrics = compute_reference_metrics(make_bars(60))

    assert metrics.sma_50 is not None
    assert metrics.sma_200 is None
    assert metrics.volume_avg_20d == 1_000_000
    assert metrics.is_complete  # SMA gaps do not make the record unusable


def test_history_shorter_than_20_days_is_incomplete():
    metrics = compute_reference_metrics(make_bars(10))

    assert metrics.volume_avg_20d is None
    assert metrics.high_20d is None
    assert metrics.price_close_yesterday is not None  # the latest bar still counts
    assert not metrics.is_complete


def test_empty_history_yields_all_none():
    metrics = compute_reference_metrics([])

    assert metrics.bars_used == 0
    assert metrics.last_bar_date is None
    assert metrics.price_close_yesterday is None
    assert not metrics.is_complete


def test_high_20d_uses_the_window_high_not_the_latest_high():
    bars = make_bars(30)
    # Spike 10 sessions back, above every other high in the window.
    bars[-11] = bars[-11].model_copy(update={"high": 999.0})

    metrics = compute_reference_metrics(bars)
    assert metrics.high_20d == 999.0
    assert metrics.high_yesterday == 115.5  # newest bar: close 114.5 + 1.0


def test_yesterday_means_the_latest_traded_session():
    """Not a calendar computation — on a Monday pre-market this is Friday's bar."""
    bars = make_bars(25)
    metrics = compute_reference_metrics(bars)

    assert metrics.last_bar_date == LATEST
    assert metrics.price_close_yesterday == bars[-1].close
