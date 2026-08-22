"""Tests for the tiered scan cadence.

This file exists because a cadence is a schedule that can be wrong in silence. A tier
boundary off by one interval, a window opening at the wrong minute, or a spec that parses
but drops the authoritative pass all produce a scanner that keeps succeeding and simply
sees less — the failure mode this project cares most about.

Four properties are pinned as properties of the code rather than of today's config values:

1. The 09:25 authoritative pass cannot be configured away.
2. The profile bucket epoch (04:00) does not move with the window start (04:15).
3. The pass count is DST-independent, because slots are built in ET wall-clock minutes.
4. A wake-up claims at most one slot.
"""

from datetime import datetime, time, timedelta, timezone

import pytest

from app.services.bars import bucket_minute
from app.services.scanner.cadence import (
    DEFAULT_CADENCE_SPEC,
    Cadence,
    CadenceError,
    CadenceTier,
    parse_cadence,
)
from app.services.scanner.clock import ET, SCAN_WINDOW_END, at_minute


def et(*args) -> datetime:
    return datetime(*args, tzinfo=ET)


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


@pytest.fixture
def cadence() -> Cadence:
    """The deployed shape, parsed from the documented default spec."""
    return parse_cadence(DEFAULT_CADENCE_SPEC)


# ------------------------------------------------------------------ the measured shape


def test_the_default_spec_is_the_measured_shape(cadence):
    """19 passes, not 66. The numbers in the brief, asserted rather than described."""
    slots = [slot.strftime("%H:%M") for slot in cadence.slots(datetime(2026, 7, 28))]

    assert slots == [
        # Hourly from the discovery pass. 04:00/04:05/04:10 are gone: with a 7-minute
        # settle window the 04:00 bar is not trusted until ~04:12, and across six live
        # sessions those three passes produced a Stage 2 survivor exactly never.
        "04:15", "05:15", "06:15",
        "07:00", "07:30",
        "08:00", "08:15",
        # The confirmation window, unchanged at 5 minutes: 73% of what it surfaces first
        # is still a candidate at the final pass.
        "08:30", "08:35", "08:40", "08:45", "08:50", "08:55",
        "09:00", "09:05", "09:10", "09:15", "09:20", "09:25",
    ]
    assert cadence.passes_per_session() == 19


def test_the_window_opens_at_0415_and_the_three_dead_passes_are_gone(cadence):
    """The part of Follow-up A that stands on its own."""
    assert cadence.start == time(4, 15)

    for dead in (et(2026, 7, 28, 4, 0), et(2026, 7, 28, 4, 5), et(2026, 7, 28, 4, 10)):
        assert cadence.is_open(dead) is False
        assert cadence.is_scheduled(dead) is False

    assert cadence.is_open(et(2026, 7, 28, 4, 15)) is True
    assert cadence.is_scheduled(et(2026, 7, 28, 4, 15)) is True


def test_every_phase_6_anchor_survives_the_coarser_cadence(cadence):
    """04:15, 07:00, 08:30 and 09:25 are the anchors `observations.py` records at.

    The cost section of the brief rests on this: coarsening the early session is only
    acceptable for Phase 5 because the well-spaced anchors are all still scanned.
    """
    for anchor in (time(4, 15), time(7, 0), time(8, 30), time(9, 25)):
        moment = et(2026, 7, 28, anchor.hour, anchor.minute)
        assert cadence.is_scheduled(moment) is True, anchor


# --------------------------------------------------- the authoritative pass is untouchable


@pytest.mark.parametrize(
    "spec",
    [
        DEFAULT_CADENCE_SPEC,
        "04:15/60",  # one coarse tier that would step 04:15 -> 05:15 -> ... past 09:25
        "04:00/5",  # the old uniform cadence
        "09:20/97",  # a single tier whose interval overshoots the close
        "04:15/23",  # an interval that divides into nothing tidily
    ],
)
def test_no_cadence_spec_can_silence_the_0925_pass(spec):
    """THE safety property. Statelessness means cadence cannot change the confirmed set —
    but only as long as the pass that computes it still runs, and that must not depend on
    a config value dividing neatly into the morning."""
    cadence = parse_cadence(spec)
    slots = cadence.slots(datetime(2026, 7, 28))

    assert slots[-1].time() == SCAN_WINDOW_END
    assert cadence.is_scheduled(et(2026, 7, 28, 9, 25)) is True


def test_the_authoritative_pass_is_scheduled_even_when_the_scheduler_is_late(cadence):
    """Render starts a job 10-45 s after its minute. 09:25:10 is still the 09:25 slot —
    the bug that made the most important pass of the day run on no production day."""
    assert cadence.is_scheduled(et(2026, 7, 28, 9, 25, 10)) is True
    assert cadence.is_scheduled(et(2026, 7, 28, 9, 25, 59, 999999)) is True
    # The minute after is out of the window entirely. Truncation, not a grace period.
    assert cadence.is_scheduled(et(2026, 7, 28, 9, 26)) is False


# ------------------------------------------------------ the bucket epoch does not move


def test_moving_the_window_start_does_not_move_the_profile_bucket_epoch():
    """`premarket_volume_profile` is keyed on minutes since 04:00 ET and holds STORED
    rows. When the window start and the bucket epoch were one constant, opening the window
    at 04:15 would have shifted every RVOL denominator lookup by three buckets — with no
    error, just confidently wrong candidates. They are separate on purpose."""
    cadence = parse_cadence("04:15/60,08:30/5")

    assert cadence.start == time(4, 15)
    # The join key is still measured from 04:00, and 04:00 is still bucket 0.
    assert bucket_minute(et(2026, 7, 28, 4, 0)) == 0
    assert bucket_minute(et(2026, 7, 28, 4, 15)) == 15
    assert bucket_minute(et(2026, 7, 28, 9, 25)) == 325


# ------------------------------------------------------------------ DST correctness


@pytest.mark.parametrize("day", [datetime(2026, 3, 8), datetime(2026, 11, 1)])
def test_the_pass_count_is_the_same_on_dst_transition_days(day, cadence):
    """Both transitions happen at 02:00 ET, outside the window — but the schedule is built
    by adding ET wall-clock minutes rather than by UTC arithmetic, which is what makes
    that true for any tier shape rather than only for a 5-minute one."""
    slots = cadence.slots(day)

    assert len(slots) == 19
    assert slots[0].time() == time(4, 15)
    assert slots[-1].time() == time(9, 25)


def test_the_same_utc_instant_falls_on_different_sides_of_the_new_window_bound(cadence):
    """The DST bug, restated against 04:15: 08:00 UTC is 03:00 ET in winter and 04:00 ET
    in summer, and neither is inside a window that now opens at 04:15. 08:20 UTC in summer
    is 04:20 ET — inside the window but off-cadence, which is the new third state."""
    assert cadence.is_open(utc(2026, 1, 15, 8, 0)) is False
    assert cadence.is_open(utc(2026, 7, 15, 8, 0)) is False

    summer_0420 = utc(2026, 7, 15, 8, 20)
    assert cadence.is_open(summer_0420) is True
    assert cadence.is_scheduled(summer_0420) is False


# ------------------------------------------------------------------ slot matching


@pytest.mark.parametrize(
    "moment,expected",
    [
        (et(2026, 7, 28, 4, 15), "04:15"),
        (et(2026, 7, 28, 4, 20), None),  # inside the window, not a scheduled pass
        (et(2026, 7, 28, 5, 15), "05:15"),
        (et(2026, 7, 28, 6, 55), None),  # the old cadence's busiest, least useful stretch
        (et(2026, 7, 28, 7, 0), "07:00"),
        (et(2026, 7, 28, 7, 15), None),  # 30-minute tier: 07:00 and 07:30 only
        (et(2026, 7, 28, 7, 30), "07:30"),
        (et(2026, 7, 28, 8, 15), "08:15"),
        (et(2026, 7, 28, 8, 20), None),  # 15-minute tier: 08:00 and 08:15 only
        (et(2026, 7, 28, 8, 45), "08:45"),  # 5-minute tier: every pass runs
        (et(2026, 7, 28, 9, 25), "09:25"),
        (et(2026, 7, 28, 11, 0), None),  # outside the window
        (et(2026, 7, 28, 3, 59), None),
    ],
)
def test_which_wake_ups_claim_a_slot(moment, expected, cadence):
    slot = cadence.slot_for(moment)

    assert (slot.strftime("%H:%M") if slot else None) == expected


def test_a_wake_up_claims_at_most_one_slot(cadence):
    """With the cron firing every 5 minutes, exactly one wake-up may claim each slot —
    otherwise a pass runs twice and the FMP fan-out is paid for twice."""
    slots = cadence.slots(datetime(2026, 7, 28))
    claims: dict[datetime, list[datetime]] = {slot: [] for slot in slots}

    # Every wake-up the `*/5` cron can produce inside the window, plus the 10-45 s of
    # scheduler lateness each one really carries.
    moment = et(2026, 7, 28, 4, 0, 23)
    # `at_minute`, not `moment.time()`: 09:25:23 is not <= 09:25:00, and comparing full
    # timestamps here would walk the loop straight past the authoritative pass — the same
    # mistake, in a test, that the production gate was fixed for.
    while at_minute(moment).time() <= SCAN_WINDOW_END:
        claimed = cadence.slot_for(moment)
        if claimed is not None:
            claims[claimed].append(moment)
        moment += timedelta(minutes=5)

    assert all(len(who) == 1 for who in claims.values()), {
        slot.strftime("%H:%M"): [m.strftime("%H:%M") for m in who]
        for slot, who in claims.items()
        if len(who) != 1
    }


def test_grace_lets_a_late_wake_up_claim_its_slot_without_double_claiming():
    """The knob exists for a scheduler late by minutes rather than seconds. It must stay
    below the cron's period: at 4 minutes the 04:20 wake-up still cannot claim 04:15."""
    forgiving = parse_cadence(DEFAULT_CADENCE_SPEC, grace_minutes=4)

    assert forgiving.slot_for(et(2026, 7, 28, 4, 19)).strftime("%H:%M") == "04:15"
    assert forgiving.slot_for(et(2026, 7, 28, 4, 20)) is None
    # The default is exact-minute, so the same late wake-up claims nothing.
    assert parse_cadence(DEFAULT_CADENCE_SPEC).slot_for(et(2026, 7, 28, 4, 19)) is None


def test_next_slot_after_names_the_pass_a_skip_message_promises(cadence):
    assert cadence.next_slot_after(et(2026, 7, 28, 4, 20)).strftime("%H:%M") == "05:15"
    assert cadence.next_slot_after(et(2026, 7, 28, 8, 46)).strftime("%H:%M") == "08:50"
    assert cadence.next_slot_after(et(2026, 7, 28, 9, 25)) is None


def test_tier_for_reports_which_tier_governs_a_moment(cadence):
    assert cadence.tier_for(et(2026, 7, 28, 4, 20)) == CadenceTier(time(4, 15), 60)
    assert cadence.tier_for(et(2026, 7, 28, 7, 45)) == CadenceTier(time(7, 0), 30)
    assert cadence.tier_for(et(2026, 7, 28, 9, 0)) == CadenceTier(time(8, 30), 5)
    assert cadence.tier_for(et(2026, 7, 28, 3, 0)) is None


# ------------------------------------------------------------------ parsing


def test_a_spec_round_trips_through_its_description():
    cadence = parse_cadence(" 04:15/60 , 07:00/30 ")

    assert cadence.tiers == (CadenceTier(time(4, 15), 60), CadenceTier(time(7, 0), 30))
    assert "04:15-09:25 ET" in cadence.describe()


@pytest.mark.parametrize(
    "spec,message",
    [
        ("", "No cadence tiers"),
        ("04:15", "missing its interval"),
        ("breakfast/60", "unreadable start time"),
        ("04:15/soon", "non-numeric interval"),
        ("04:15/0", "positive interval"),
        ("04:15/-5", "positive interval"),
        ("07:00/30,04:15/60", "must ascend"),
        ("04:15/60,04:15/30", "must ascend"),
        ("09:25/5", "so it would never run"),
        ("10:00/5", "so it would never run"),
    ],
)
def test_an_unhonourable_spec_is_rejected_by_name(spec, message):
    """Every one of these is a deployment-time typo in an env var. Failing loudly at
    startup is the point: a cadence that silently parses to "no scans" would look exactly
    like a quiet market for as long as nobody checked."""
    with pytest.raises(CadenceError, match=message):
        parse_cadence(spec)


def test_the_configured_default_is_the_documented_default():
    """The spec string appears in config.py, render.yaml and the docs. If the module
    default drifts away from the setting, the comments stop describing the deployment."""
    from app.config import get_settings

    assert get_settings().scan_cadence_tiers == DEFAULT_CADENCE_SPEC
