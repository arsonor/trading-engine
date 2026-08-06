"""The settled-bar rule and pre-market bucketing.

The boundary cases here are not pedantry. Phase 4A measured that half of all pre-market
bars are revised upward after publication, settling within 7 minutes of bar close. Get the
boundary wrong by one interval and RVOL is biased low on exactly the bars that signal a
stock is moving — see the module docstring of `app/services/bars.py` for why both sides of
that division must agree.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.config import Settings
from app.services.bars import (
    Bar,
    bucket_minute,
    cumulative_by_bucket,
    is_premarket,
    is_settled,
    premarket_bars,
    settled_bars,
)

ET = ZoneInfo("America/New_York")


def at(hour: int, minute: int, day: int = 6) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=ET)


def bar(hour: int, minute: int, volume: float = 100.0, interval: int = 5) -> Bar:
    return Bar(start=at(hour, minute), volume=volume, interval_minutes=interval)


# ------------------------------------------------------------------ bucketing


def test_bucket_zero_is_the_four_am_open():
    assert bucket_minute(at(4, 0)) == 0


def test_buckets_count_minutes_since_four_am():
    assert bucket_minute(at(4, 5)) == 5
    assert bucket_minute(at(9, 25)) == 325


def test_bucket_before_open_is_negative_not_clamped():
    """Folding 03:55 into bucket 0 would contaminate the profile's first bucket with
    volume from outside the session."""
    assert bucket_minute(at(3, 55)) == -5


def test_premarket_window_boundaries_are_inclusive_open_exclusive_close():
    assert is_premarket(at(4, 0)) is True
    assert is_premarket(at(9, 29)) is True
    assert is_premarket(at(9, 30)) is False
    assert is_premarket(at(3, 59)) is False


def test_premarket_bars_filters_and_sorts():
    bars = [bar(9, 35), bar(4, 10), bar(3, 30), bar(4, 0)]
    assert [b.start.hour * 60 + b.start.minute for b in premarket_bars(bars)] == [240, 250]


# ------------------------------------------------------------------ bar close


def test_bar_end_is_the_opening_edge_plus_the_interval():
    """FMP stamps bars at their opening edge; a 04:00 five-minute bar closes at 04:05."""
    assert bar(4, 0).end == at(4, 5)
    assert bar(4, 0, interval=1).end == at(4, 1)


# ------------------------------------------------------------------ the settling boundary


def test_bar_still_forming_is_never_settled():
    assert is_settled(bar(4, 0), now=at(4, 3), exclusion_minutes=7) is False


def test_bar_just_closed_is_not_yet_settled():
    """Closed at 04:05, but revisions were measured up to 7 minutes after close."""
    assert is_settled(bar(4, 0), now=at(4, 5), exclusion_minutes=7) is False


def test_one_minute_before_the_window_expires_is_not_settled():
    assert is_settled(bar(4, 0), now=at(4, 11), exclusion_minutes=7) is False


def test_exactly_at_the_window_is_settled():
    """THE boundary: close 04:05 + 7 minutes = 04:12. Inclusive."""
    assert is_settled(bar(4, 0), now=at(4, 12), exclusion_minutes=7) is True


def test_after_the_window_is_settled():
    assert is_settled(bar(4, 0), now=at(4, 30), exclusion_minutes=7) is True


def test_zero_exclusion_settles_at_bar_close():
    """A deployment that trusts the vendor can set the window to 0; the rule must still
    refuse a bar that has not finished forming."""
    assert is_settled(bar(4, 0), now=at(4, 4), exclusion_minutes=0) is False
    assert is_settled(bar(4, 0), now=at(4, 5), exclusion_minutes=0) is True


# ------------------------------------------------------------------ settled_bars


def test_settled_bars_drops_only_the_provisional_tail():
    bars = [bar(4, 0), bar(4, 5), bar(4, 10), bar(4, 15)]
    # 04:20 now: 04:00 closes 04:05 (+7 = 04:12 ok), 04:05 closes 04:10 (+7 = 04:17 ok),
    # 04:10 closes 04:15 (+7 = 04:22 NOT yet), 04:15 still forming.
    kept = settled_bars(bars, now=at(4, 20), exclusion_minutes=7)
    assert [b.start for b in kept] == [at(4, 0), at(4, 5)]


def test_settled_bars_without_a_clock_treats_everything_as_historical():
    """How the profile builder calls it: previous sessions are fully settled."""
    bars = [bar(4, 10), bar(4, 0)]
    assert [b.start for b in settled_bars(bars)] == [at(4, 0), at(4, 10)]


def test_settled_bars_sorts_its_output():
    kept = settled_bars([bar(4, 15), bar(4, 0), bar(4, 5)], now=at(6, 0))
    assert [b.start for b in kept] == [at(4, 0), at(4, 5), at(4, 15)]


def test_exclusion_window_comes_from_config_not_a_literal(monkeypatch):
    """The 7-minute figure is one session's measurement. A deployment must be able to
    widen it without a code change."""
    from app.services import bars as bars_module

    monkeypatch.setattr(bars_module, "get_settings", lambda: Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db", bar_settle_minutes=30
    ))
    # Closes 04:05; with a 30-minute window it is not settled until 04:35.
    assert is_settled(bar(4, 0), now=at(4, 20)) is False
    assert is_settled(bar(4, 0), now=at(4, 35)) is True


# ------------------------------------------------------------------ cumulative sum


def test_cumulative_is_a_running_sum_because_volume_is_per_bar():
    """Phase 4A's measurement: consecutive bars fall (30,243 -> 9,965 -> 2,822), which a
    cumulative counter cannot do. Reading one bar's volume as 'so far' yields the last
    five minutes instead of the session."""
    bars = [bar(4, 0, 30_243), bar(4, 5, 9_965), bar(4, 10, 2_822)]

    assert cumulative_by_bucket(bars) == {0: 30_243, 5: 40_208, 10: 43_030}


def test_cumulative_ignores_bars_outside_the_premarket_window():
    bars = [bar(3, 55, 999), bar(4, 0, 100), bar(9, 35, 999)]

    assert cumulative_by_bucket(bars) == {0: 100}


def test_cumulative_handles_a_gap_in_trading():
    """A thin small cap may not print every interval. Buckets it never traded in are
    absent rather than zero, so the profile averages only observed points."""
    bars = [bar(4, 0, 50), bar(4, 20, 25)]

    assert cumulative_by_bucket(bars) == {0: 50, 20: 75}


def test_cumulative_of_nothing_is_empty():
    assert cumulative_by_bucket([]) == {}


@pytest.mark.parametrize("volume", [0, 0.0])
def test_zero_volume_bar_still_registers_a_bucket(volume):
    """A printed bar with zero volume is a real observation — the ticker was quoted and
    did not trade. Dropping it would make the profile look sparser than it is."""
    assert cumulative_by_bucket([bar(4, 0, volume)]) == {0: 0.0}
