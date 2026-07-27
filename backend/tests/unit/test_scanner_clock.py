"""Tests for market-time handling.

DST is the reason this file exists. Render's cron runs in UTC; the market runs in ET.
A UTC-pinned schedule silently slides an hour twice a year, which for a scanner gated on
a 04:00-09:25 window means firing outside the window for half the year — a correctness
bug that produces no error, just silence.
"""

from datetime import datetime, timezone

import pytest

from app.services.scanner.clock import (
    ET,
    FixedClock,
    SystemClock,
    describe,
    is_final_pass,
    is_within_scan_window,
    minutes_since_window_open,
    parse_scan_time,
    scan_times_for,
    to_et,
    to_utc,
)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


def et(*args) -> datetime:
    return datetime(*args, tzinfo=ET)


# ------------------------------------------------------------------ DST correctness


def test_the_same_utc_time_is_a_different_et_time_across_dst():
    """This is the whole bug in one assertion: 08:00 UTC is 03:00 ET in January and
    04:00 ET in July, so a UTC-pinned schedule straddles the window boundary."""
    winter = to_et(utc(2026, 1, 15, 8, 0))
    summer = to_et(utc(2026, 7, 15, 8, 0))

    assert (winter.hour, winter.tzname()) == (3, "EST")
    assert (summer.hour, summer.tzname()) == (4, "EDT")

    assert is_within_scan_window(winter) is False  # 03:00 — before the window opens
    assert is_within_scan_window(summer) is True  # 04:00 — the window's first minute


def test_spring_forward_transition_resolves_correctly():
    """2026-03-08: 02:00 ET jumps to 03:00 ET. The window opens at 04:00 either way."""
    before = to_et(utc(2026, 3, 8, 6, 30))  # 01:30 EST
    after = to_et(utc(2026, 3, 8, 7, 30))  # 03:30 EDT

    assert (before.hour, before.minute, before.tzname()) == (1, 30, "EST")
    assert (after.hour, after.minute, after.tzname()) == (3, 30, "EDT")
    assert before.utcoffset().total_seconds() == -5 * 3600
    assert after.utcoffset().total_seconds() == -4 * 3600

    # 08:00 UTC on transition day is 04:00 EDT — the window opens.
    assert is_within_scan_window(to_et(utc(2026, 3, 8, 8, 0))) is True


def test_fall_back_transition_resolves_correctly():
    """2026-11-01: 02:00 EDT falls back to 01:00 EST, so 01:30 ET happens twice."""
    first = to_et(utc(2026, 11, 1, 5, 30))  # 01:30 EDT
    second = to_et(utc(2026, 11, 1, 6, 30))  # 01:30 EST

    assert (first.hour, first.minute, first.tzname()) == (1, 30, "EDT")
    assert (second.hour, second.minute, second.tzname()) == (1, 30, "EST")

    # Same wall clock, one hour apart in real time. PEP 495 makes same-zone `==` ignore
    # `fold`, so the ambiguity is only visible through the UTC instant — which is exactly
    # why the scanner keeps aware datetimes and converts, rather than comparing naive ones.
    assert first.utcoffset().total_seconds() == -4 * 3600
    assert second.utcoffset().total_seconds() == -5 * 3600
    assert (second.astimezone(timezone.utc) - first.astimezone(timezone.utc)).seconds == 3600

    # After the transition, 13:00 UTC is 08:00 EST — inside the window.
    assert is_within_scan_window(to_et(utc(2026, 11, 1, 13, 0))) is True


def test_scan_window_start_in_utc_shifts_by_an_hour_across_dst():
    """The practical consequence for render.yaml: 04:00 ET is 09:00 UTC in winter and
    08:00 UTC in summer, so the cron must be scheduled generously and gated in code."""
    assert to_utc(et(2026, 1, 15, 4, 0)).hour == 9
    assert to_utc(et(2026, 7, 15, 4, 0)).hour == 8


@pytest.mark.parametrize("day", [datetime(2026, 3, 8), datetime(2026, 11, 1)])
def test_scan_schedule_has_the_same_run_count_on_dst_days(day):
    """04:00 -> 09:25 every 5 minutes is 66 runs, transition day or not, because the
    schedule is built in ET wall-clock minutes rather than by UTC arithmetic."""
    times = scan_times_for(day)

    assert len(times) == 66
    assert times[0].time().isoformat("minutes") == "04:00"
    assert times[-1].time().isoformat("minutes") == "09:25"


# ------------------------------------------------------------------ window gating


@pytest.mark.parametrize(
    "moment,expected",
    [
        (et(2026, 7, 28, 3, 59), False),
        (et(2026, 7, 28, 4, 0), True),  # inclusive: the window opens at 04:00
        (et(2026, 7, 28, 6, 30), True),
        (et(2026, 7, 28, 9, 25), True),  # inclusive: the final pass must run
        (et(2026, 7, 28, 9, 26), False),
        (et(2026, 7, 28, 15, 0), False),
    ],
)
def test_scan_window_boundaries_are_inclusive(moment, expected):
    assert is_within_scan_window(moment) is expected


def test_final_pass_starts_at_0925():
    assert is_final_pass(et(2026, 7, 28, 9, 24)) is False
    assert is_final_pass(et(2026, 7, 28, 9, 25)) is True


def test_minutes_since_window_open_indexes_volume_profile_buckets():
    assert minutes_since_window_open(et(2026, 7, 28, 4, 0)) == 0
    assert minutes_since_window_open(et(2026, 7, 28, 8, 45)) == 285
    assert minutes_since_window_open(et(2026, 7, 28, 9, 25)) == 325


# ------------------------------------------------------------------ conversion + parsing


def test_naive_datetimes_are_read_as_et_not_utc():
    """Every naive timestamp here comes from a human typing a market time. Reading
    '08:45' as UTC would move the scan four hours."""
    parsed = to_et(datetime(2026, 7, 28, 8, 45))

    assert parsed.tzname() == "EDT"
    assert parsed.hour == 8


@pytest.mark.parametrize(
    "raw",
    [
        "2026-07-28 08:45",
        "2026-07-28 08:45 ET",
        "2026-07-28T08:45",
        "2026-07-28 08:45 EDT",
    ],
)
def test_parse_scan_time_accepts_the_documented_forms(raw):
    parsed = parse_scan_time(raw)

    assert (parsed.year, parsed.month, parsed.day) == (2026, 7, 28)
    assert (parsed.hour, parsed.minute) == (8, 45)
    assert parsed.tzname() == "EDT"


def test_parse_scan_time_honours_an_explicit_offset():
    parsed = parse_scan_time("2026-07-28T12:45:00+00:00")

    assert parsed.hour == 8  # 12:45 UTC is 08:45 EDT
    assert parsed.tzname() == "EDT"


def test_parse_scan_time_rejects_garbage_with_an_example():
    with pytest.raises(ValueError, match="2026-07-28 08:45"):
        parse_scan_time("next tuesday morning")


# ------------------------------------------------------------------ clocks


def test_fixed_clock_freezes_time():
    clock = FixedClock(datetime(2026, 7, 28, 8, 45))

    assert clock.now_et() == clock.now_et()
    assert clock.now_et().hour == 8


def test_fixed_clock_converts_utc_input_to_et():
    clock = FixedClock(utc(2026, 7, 28, 12, 45))

    assert clock.now_et().hour == 8
    assert clock.now_et().tzname() == "EDT"


def test_system_clock_returns_timezone_aware_et():
    now = SystemClock().now_et()

    assert now.tzinfo is not None
    assert now.tzname() in {"EST", "EDT"}


def test_describe_always_shows_which_dst_offset_is_in_play():
    assert describe(et(2026, 1, 15, 8, 45)) == "2026-01-15 08:45 EST (UTC-05)"
    assert describe(et(2026, 7, 15, 8, 45)) == "2026-07-15 08:45 EDT (UTC-04)"
