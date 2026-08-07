"""Tests for the pluggable RVOL calculators.

The point of this seam is that upgrading FMP tiers is a config change. These tests pin
both halves of that promise: `simple` works and admits it is approximate, and `normalized`
never quietly produces a number that claims to be time-of-day normalized when it is not.

Since Phase 4C the strict and the forgiving behaviours are two classes. `NormalizedRvol`
still refuses outright; `NormalizedRvolWithFallback` — what the factory returns, and what
a live scan uses — degrades to simple and says so, because refusing outright would drop
exactly the newly-listed names the strategy wants and that have no profile yet.
"""

from datetime import datetime

import pytest

from app.config import Settings
from app.services.scanner.errors import FeatureRequiresIntraday, InsufficientRvolData
from app.services.scanner.rvol import (
    MODE_NORMALIZED,
    MODE_SIMPLE,
    NormalizedRvol,
    NormalizedRvolWithFallback,
    RvolContext,
    SimpleRvol,
    get_rvol_calculator,
)


def context(**overrides) -> RvolContext:
    base = {
        "ticker": "AAPL",
        "volume_premarket_accumulated": 250_000,
        "volume_avg_20d": 1_000_000,
    }
    base.update(overrides)
    return RvolContext(**base)


def test_simple_rvol_is_a_percentage_of_the_20d_average():
    result = SimpleRvol().compute(context())

    assert result.rvol_pct == 25.0
    assert result.mode == MODE_SIMPLE


def test_simple_rvol_is_always_flagged_approximate():
    """Comparing a partial pre-market session to a full-day average is not exact, and
    the alert payload must carry that admission all the way to the UI."""
    result = SimpleRvol().compute(context())

    assert result.is_approximate is True
    assert "not time-of-day normalized" in result.detail


def test_simple_rvol_refuses_when_average_volume_is_missing():
    """A ticker with no 20-day average must be skipped, never scored as 0% RVOL."""
    with pytest.raises(InsufficientRvolData):
        SimpleRvol().compute(context(volume_avg_20d=None))

    with pytest.raises(InsufficientRvolData):
        SimpleRvol().compute(context(volume_avg_20d=0))


def test_simple_rvol_refuses_when_premarket_volume_is_missing():
    with pytest.raises(InsufficientRvolData):
        SimpleRvol().compute(context(volume_premarket_accumulated=None))


def test_strict_normalized_rvol_refuses_without_a_profile_and_says_how_to_get_one():
    """The strict class still raises. What changed in 4C is the REASON: Premium is active
    and profiles exist, so a missing profile is now a per-ticker gap the nightly build
    fills, not a tier the account has not bought."""
    with pytest.raises(FeatureRequiresIntraday) as exc_info:
        NormalizedRvol().compute(context())

    message = str(exc_info.value)
    assert "build_volume_profiles.py" in message
    assert "extended=true" in message


def test_normalized_rvol_computes_against_the_time_of_day_bucket():
    """The V3 path: 08:00 ET is 240 minutes past the 04:00 open."""
    result = NormalizedRvol().compute(
        context(
            as_of=datetime(2026, 7, 24, 8, 0),
            premarket_volume_profile={0: 1_000.0, 120: 50_000.0, 240: 125_000.0},
        )
    )

    assert result.rvol_pct == 200.0
    assert result.mode == MODE_NORMALIZED
    assert result.is_approximate is False


def test_normalized_rvol_uses_the_nearest_earlier_bucket():
    result = NormalizedRvol().compute(
        context(
            as_of=datetime(2026, 7, 24, 8, 3),  # 243 minutes — falls between buckets
            premarket_volume_profile={120: 50_000.0, 240: 125_000.0, 300: 500_000.0},
        )
    )

    assert result.rvol_pct == 200.0  # the 240 bucket, not the 300 one


def test_normalized_rvol_needs_a_timestamp():
    with pytest.raises(InsufficientRvolData):
        NormalizedRvol().compute(context(premarket_volume_profile={0: 1.0}))


def test_factory_resolves_modes_by_name():
    """The factory's contract is the MODE it yields, not the concrete class. `normalized`
    resolves to the fallback-capable calculator so a live scan does not lose candidates
    whose profiles have not been built yet."""
    assert get_rvol_calculator("simple").mode == MODE_SIMPLE
    assert get_rvol_calculator("NORMALIZED").mode == MODE_NORMALIZED
    assert isinstance(get_rvol_calculator("simple"), SimpleRvol)
    assert isinstance(get_rvol_calculator("NORMALIZED"), NormalizedRvolWithFallback)


def test_factory_rejects_unknown_modes():
    with pytest.raises(ValueError, match="Unknown RVOL mode"):
        get_rvol_calculator("magic")


def test_factory_defaults_to_the_configured_mode(monkeypatch):
    """The factory follows RVOL_MODE.

    Pinned against an explicit Settings rather than the ambient `.env`: this test used to
    assert the default was `simple`, which was true of V1 and stopped being true the moment
    Phase 4C set `RVOL_MODE=normalized`. A test that reads the developer's environment
    reports on that environment, not on the code.
    """
    from app.services.scanner import rvol as rvol_module

    def with_mode(mode: str):
        return lambda: Settings(
            database_url="postgresql+asyncpg://u:p@localhost:5432/db", rvol_mode=mode
        )

    monkeypatch.setattr(rvol_module, "get_settings", with_mode("simple"))
    assert get_rvol_calculator().mode == MODE_SIMPLE

    monkeypatch.setattr(rvol_module, "get_settings", with_mode("normalized"))
    assert get_rvol_calculator().mode == MODE_NORMALIZED


def test_the_default_calculator_never_raises_on_a_missing_profile():
    """Whichever mode is configured, a candidate must not be lost because its profile has
    not been built yet — it degrades and is flagged instead."""
    for mode in (MODE_SIMPLE, MODE_NORMALIZED):
        result = get_rvol_calculator(mode).compute(context(as_of=et(6, 0)))
        assert result.is_approximate is True


# ===================================================== the settled-bar symmetry rule

# Phase 4A measured that 49.4% of pre-market bars are revised upward after publication,
# settling within ~7 minutes of bar close. So a live numerator is only honest up to an
# instant EARLIER than the scan time. The profile denominator is built from fully-settled
# history. If the two are read at different clock times, RVOL is wrong by however much the
# market normally trades in the gap — silently, and always in the direction of fewer
# alerts.


def profile_curve() -> dict[int, float]:
    """A profile that grows 1,000 shares per 5-minute bucket from 04:00 to 09:25."""
    return {b: float(1_000 * (b // 5 + 1)) for b in range(0, 330, 5)}


def et(hour: int, minute: int) -> datetime:
    return datetime(2026, 8, 6, hour, minute)


def test_matching_volume_scores_about_one_hundred_percent():
    """DoD: live volume equal to the profile must read ~100%, not 80% or 120%."""
    for hour, minute in [(4, 30), (6, 0), (8, 15), (9, 25)]:
        bucket = (hour - 4) * 60 + minute
        expected = profile_curve()[bucket - bucket % 5]
        result = NormalizedRvol().compute(context(
            volume_premarket_accumulated=expected,
            as_of=et(hour, minute),
            settled_through=et(hour, minute),
            premarket_volume_profile=profile_curve(),
        ))
        assert result.rvol_pct == pytest.approx(100.0), f"at {hour:02d}:{minute:02d}"


def test_the_denominator_follows_settled_through_not_as_of():
    """THE symmetry test. It fails if the bucket is chosen from the scan time while the
    numerator only covers up to the settled cut-off."""
    profile = profile_curve()
    # Scan at 09:25, but bars are only settled through 09:00 — 25 minutes of lag.
    volume_through_0900 = profile[300]

    result = NormalizedRvol().compute(context(
        volume_premarket_accumulated=volume_through_0900,
        as_of=et(9, 25),
        settled_through=et(9, 0),
        premarket_volume_profile=profile,
    ))

    # Correct: compare like with like -> 100%.
    assert result.rvol_pct == pytest.approx(100.0)

    # And the bug this guards: keying the lookup off `as_of` would divide by the 09:25
    # bucket instead, understating a perfectly average ticker.
    understated = volume_through_0900 / profile[325] * 100
    assert understated == pytest.approx(92.4, abs=0.1)
    assert result.rvol_pct - understated > 5.0

    # 7.6% on this deliberately LINEAR profile. Real curves accelerate into the open —
    # AAPL's measured profile runs 8,620 shares at 04:00 to 301,625 at 09:25 — so the same
    # 25-minute lag costs far more there, and always in the direction of fewer alerts.


def test_without_a_settled_cut_off_the_scan_time_is_used():
    """The fixture provider authors complete volumes, so `as_of` is the honest reference
    there. Absence of `settled_through` must not silently shift the bucket."""
    profile = profile_curve()

    result = NormalizedRvol().compute(context(
        volume_premarket_accumulated=profile[120],
        as_of=et(6, 0),
        premarket_volume_profile=profile,
    ))

    assert result.rvol_pct == pytest.approx(100.0)


def test_normalized_result_is_not_flagged_approximate():
    result = NormalizedRvol().compute(context(
        as_of=et(6, 0), settled_through=et(6, 0), premarket_volume_profile=profile_curve()
    ))

    assert result.is_approximate is False
    assert result.mode == MODE_NORMALIZED


# ===================================================== degradation, never silent mixing


def test_missing_profile_degrades_to_simple_and_says_so():
    result = NormalizedRvolWithFallback().compute(context(as_of=et(6, 0)))

    assert result.mode == MODE_SIMPLE, "must not claim to be normalized"
    assert result.is_approximate is True, "the UI badge depends on this"
    assert "DEGRADED" in result.detail
    assert "no pre-market volume profile" in result.detail


def test_thin_profile_degrades_rather_than_dividing_by_noise():
    """A 3-session profile is not a worse 20-session profile; it is a much noisier
    quantity that RVOL would divide by with full confidence."""
    result = NormalizedRvolWithFallback().compute(context(
        as_of=et(6, 0),
        settled_through=et(6, 0),
        premarket_volume_profile=profile_curve(),
        profile_sessions_sampled=3,
    ))

    assert result.mode == MODE_SIMPLE
    assert "only 3 session" in result.detail


def test_a_healthy_profile_is_not_degraded():
    result = NormalizedRvolWithFallback().compute(context(
        volume_premarket_accumulated=profile_curve()[120],
        as_of=et(6, 0),
        settled_through=et(6, 0),
        premarket_volume_profile=profile_curve(),
        profile_sessions_sampled=20,
    ))

    assert result.mode == MODE_NORMALIZED
    assert result.is_approximate is False
    assert "DEGRADED" not in result.detail
    assert result.rvol_pct == pytest.approx(100.0)
