"""Pre-market volume profile averaging.

This is the DENOMINATOR of normalized RVOL. Every bug here shows up as a confident wrong
number rather than an error: too low a denominator inflates RVOL and floods the alert list,
too high suppresses it. The averaging rules are therefore pinned individually.
"""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.services.bars import Bar
from app.services.reference.volume_profile import VolumeProfileBuilder

ET = ZoneInfo("America/New_York")


def bar(day: int, hour: int, minute: int, volume: float) -> Bar:
    return Bar(start=datetime(2026, 8, day, hour, minute, tzinfo=ET), volume=volume)


def builder() -> VolumeProfileBuilder:
    # No client call is made by `average_profile`; None is enough and keeps the test pure.
    return VolumeProfileBuilder(client=None, session_factory=lambda: None)


def test_single_session_profile_is_that_session_cumulative_curve():
    sessions = {date(2026, 8, 3): [bar(3, 4, 0, 100), bar(3, 4, 5, 50), bar(3, 4, 10, 25)]}

    profile, used = builder().average_profile(sessions, target_sessions=20)

    assert used == 1
    assert profile == {0: 100.0, 5: 150.0, 10: 175.0}


def test_two_sessions_are_averaged_bucket_by_bucket():
    sessions = {
        date(2026, 8, 3): [bar(3, 4, 0, 100), bar(3, 4, 5, 100)],
        date(2026, 8, 4): [bar(4, 4, 0, 200), bar(4, 4, 5, 200)],
    }

    profile, used = builder().average_profile(sessions, target_sessions=20)

    assert used == 2
    # Cumulative per session is {0:100, 5:200} and {0:200, 5:400}; averaged.
    assert profile == {0: 150.0, 5: 300.0}


def test_a_bucket_is_averaged_only_over_sessions_that_reached_it():
    """The subtle one. A ticker that did not trade before 06:00 on one day must not have
    that day counted as a zero at 04:00 — that would drag the denominator down and inflate
    RVOL for every morning afterwards."""
    sessions = {
        date(2026, 8, 3): [bar(3, 4, 0, 100)],          # traded at 04:00
        date(2026, 8, 4): [bar(4, 6, 0, 900)],          # first traded at 06:00
    }

    profile, _ = builder().average_profile(sessions, target_sessions=20)

    # Bucket 0 saw one session, bucket 120 (06:00) saw one session. Neither is halved.
    assert profile[0] == 100.0
    assert profile[120] == 900.0


def test_only_the_newest_target_sessions_are_used():
    sessions = {
        date(2026, 8, d): [bar(d, 4, 0, float(d))] for d in (3, 4, 5, 6)
    }

    profile, used = builder().average_profile(sessions, target_sessions=2)

    assert used == 2
    # Newest two are the 5th and 6th: (5 + 6) / 2.
    assert profile[0] == 5.5


def test_bars_outside_the_premarket_window_are_excluded():
    sessions = {
        date(2026, 8, 3): [bar(3, 3, 55, 999), bar(3, 4, 0, 10), bar(3, 10, 0, 999)]
    }

    profile, _ = builder().average_profile(sessions, target_sessions=20)

    assert profile == {0: 10.0}


def test_empty_sessions_produce_an_empty_profile():
    profile, used = builder().average_profile({}, target_sessions=20)

    assert profile == {}
    assert used == 0


def test_session_with_no_premarket_bars_contributes_nothing():
    """Counted as a session that was fetched, but it adds no buckets — so it cannot
    silently dilute the average of the sessions that did trade."""
    sessions = {
        date(2026, 8, 3): [bar(3, 4, 0, 100)],
        date(2026, 8, 4): [bar(4, 11, 0, 5000)],  # regular hours only
    }

    profile, used = builder().average_profile(sessions, target_sessions=20)

    assert used == 2
    assert profile == {0: 100.0}


def test_profile_curve_is_non_decreasing():
    """A cumulative curve that falls would mean volume was un-traded. Averaging must not
    break the property, since RVOL reads consecutive buckets."""
    sessions = {
        date(2026, 8, 3): [bar(3, 4, 0, 10), bar(3, 4, 5, 0), bar(3, 4, 10, 30)],
        date(2026, 8, 4): [bar(4, 4, 0, 5), bar(4, 4, 5, 40), bar(4, 4, 10, 1)],
    }

    profile, _ = builder().average_profile(sessions, target_sessions=20)

    values = [profile[b] for b in sorted(profile)]
    assert values == sorted(values)


def test_zero_volume_bars_still_hold_the_curve_flat_rather_than_creating_a_gap():
    sessions = {date(2026, 8, 3): [bar(3, 4, 0, 100), bar(3, 4, 5, 0)]}

    profile, _ = builder().average_profile(sessions, target_sessions=20)

    assert profile == {0: 100.0, 5: 100.0}
