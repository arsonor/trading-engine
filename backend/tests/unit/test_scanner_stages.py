"""Golden-case boundary tests for the three stages.

Every threshold in `docs/CLAUDE.md` section 4.3 is tested at its exact boundary value.
This is the file that stops "gap >= 3.0" from quietly becoming "gap > 3.0": both read the
same in a code review, produce different candidate sets, and nothing fails loudly when
they diverge.

The convention, taken literally from the spec:

    static_float   < 75,000,000       -> exactly 75M FAILS
    volume_avg_20d > 500,000          -> exactly 500k FAILS
    3.0 <= gap_pct <= 15.0            -> exactly 3.0 and exactly 15.0 PASS
    rvol_pct       > 10.0             -> exactly 10.0 FAILS
    upside_pct     >= 5.5             -> exactly 5.5 PASSES
"""

from datetime import datetime

import pytest

from app.services.scanner.candidate import STAGE_2, STAGE_3, Candidate
from app.services.scanner.profiles import production_profile
from app.services.scanner.rvol import SimpleRvol
from app.services.scanner.snapshot import MarketSnapshot
from app.services.scanner.stages import stage_2_momentum, stage_3_room_to_run

AS_OF = datetime(2026, 7, 28, 8, 45)


@pytest.fixture
def profile():
    return production_profile()


def candidate(**overrides) -> Candidate:
    base = {
        "ticker": "TEST",
        "static_float": 40_000_000,
        "volume_avg_20d": 1_000_000.0,
        "price_close_yesterday": 100.0,
        "high_yesterday": 101.0,
        "high_20d": 120.0,
        "sma_50": 99.0,
        "sma_200": 95.0,
    }
    base.update(overrides)
    return Candidate(**base)


def snapshot(price: float, volume: float, ticker: str = "TEST") -> dict:
    return {
        ticker: MarketSnapshot(
            ticker=ticker,
            price=price,
            volume_premarket_accumulated=volume,
            as_of=AS_OF,
            source="fixture",
        )
    }


def run_stage_2(cand: Candidate, price: float, volume: float, profile):
    return stage_2_momentum(
        [cand], snapshot(price, volume, cand.ticker), profile, SimpleRvol(), AS_OF
    )


# ------------------------------------------------------------------ Stage 2: gap band


@pytest.mark.parametrize(
    "price,gap,should_pass",
    [
        (102.99, 2.99, False),  # just under the floor
        (103.00, 3.00, True),  # EXACTLY the floor — inclusive, passes
        (110.00, 10.00, True),
        (115.00, 15.00, True),  # EXACTLY the ceiling — inclusive, passes
        (115.01, 15.01, False),  # just over the ceiling
    ],
)
def test_gap_band_boundaries_are_inclusive(price, gap, should_pass, profile):
    outcome = run_stage_2(candidate(), price, 250_000, profile)

    assert bool(outcome.survivors) is should_pass
    if should_pass:
        assert outcome.survivors[0].gap_pct == pytest.approx(gap)
    else:
        assert outcome.rejections[0].reason == "gap outside band"


def test_a_gap_down_is_rejected(profile):
    outcome = run_stage_2(candidate(), 95.0, 250_000, profile)

    assert not outcome.survivors
    assert outcome.rejections[0].reason == "gap outside band"


# ------------------------------------------------------------------ Stage 2: RVOL


@pytest.mark.parametrize(
    "volume,rvol,should_pass",
    [
        (99_999, 9.9999, False),
        (100_000, 10.0, False),  # EXACTLY the threshold — strictly greater, so FAILS
        (100_001, 10.0001, True),  # the smallest passing value
        (250_000, 25.0, True),
    ],
)
def test_rvol_threshold_is_strictly_greater(volume, rvol, should_pass, profile):
    outcome = run_stage_2(candidate(), 105.0, volume, profile)

    assert bool(outcome.survivors) is should_pass
    if should_pass:
        assert outcome.survivors[0].rvol_pct == pytest.approx(rvol)
    else:
        assert outcome.rejections[0].reason == "rvol too low"


def test_rvol_carries_its_approximation_flag_onto_the_candidate(profile):
    """The honesty metadata has to survive the stage, not just the calculator."""
    outcome = run_stage_2(candidate(), 105.0, 250_000, profile)
    survivor = outcome.survivors[0]

    assert survivor.rvol_mode == "simple"
    assert survivor.rvol_is_approximate is True
    assert "not time-of-day normalized" in survivor.rvol_detail


# ------------------------------------------------------------------ Stage 3: upside


@pytest.mark.parametrize(
    "resistance,upside,should_pass",
    [
        (105.0 * 1.0549, 5.49, False),
        (105.0 * 1.055, 5.5, True),  # EXACTLY the threshold — inclusive, passes
        (120.0, 14.2857, True),
    ],
)
def test_upside_threshold_is_inclusive(resistance, upside, should_pass, profile):
    cand = candidate(high_20d=resistance, high_yesterday=101.0, sma_50=99.0, sma_200=95.0)
    cand.price_premarket_current = 105.0

    outcome = stage_3_room_to_run([cand], profile)

    assert bool(outcome.survivors) is should_pass
    assert cand.upside_pct == pytest.approx(upside, abs=1e-3)


def test_boundary_survives_floating_point_noise(profile):
    """`105 * 1.055 - 105` computes an upside of 5.499999999999996. Compared raw, that
    rejects a candidate whose card reads "5.50%" against a documented 5.5% bar. The
    comparison rounds first so the displayed number and the decision agree."""
    cand = candidate(high_20d=105.0 * 1.055, high_yesterday=101.0, sma_50=99.0, sma_200=95.0)
    cand.price_premarket_current = 105.0

    outcome = stage_3_room_to_run([cand], profile)

    assert cand.upside_pct == 5.5
    assert outcome.survivors


def test_gap_floor_survives_floating_point_noise(profile):
    outcome = run_stage_2(candidate(), 103.0, 250_000, profile)

    assert outcome.survivors
    assert outcome.survivors[0].gap_pct == 3.0


def test_nearest_resistance_is_the_lowest_level_above_price(profile):
    cand = candidate(high_yesterday=110.0, high_20d=120.0, sma_50=115.0, sma_200=130.0)
    cand.price_premarket_current = 105.0

    stage_3_room_to_run([cand], profile)

    assert cand.nearest_resistance == 110.0
    assert cand.resistance_source == "high_yesterday"


def test_levels_at_or_below_the_price_are_not_resistance(profile):
    """A level exactly at the current price is not overhead — it has been reached."""
    cand = candidate(high_yesterday=101.0, high_20d=120.0, sma_50=105.0, sma_200=95.0)
    cand.price_premarket_current = 105.0

    stage_3_room_to_run([cand], profile)

    assert cand.nearest_resistance == 120.0  # sma_50 == price is excluded
    assert cand.resistance_source == "high_20d"


def test_a_ticker_above_every_level_is_rejected_not_given_infinite_upside(profile):
    cand = candidate(high_yesterday=101.0, high_20d=104.0, sma_50=99.0, sma_200=95.0)
    cand.price_premarket_current = 105.0

    outcome = stage_3_room_to_run([cand], profile)

    assert not outcome.survivors
    assert outcome.rejections[0].reason == "no resistance above price"
    assert cand.upside_pct is None


def test_missing_smas_still_allow_a_verdict_from_the_remaining_levels(profile):
    """A recently listed ticker has no SMA-200; that is a narrower view, not a failure."""
    cand = candidate(sma_50=None, sma_200=None, high_yesterday=101.0, high_20d=120.0)
    cand.price_premarket_current = 105.0

    outcome = stage_3_room_to_run([cand], profile)

    assert outcome.survivors
    assert cand.resistance_source == "high_20d"


# ------------------------------------------------------------------ degraded inputs


def test_a_ticker_with_no_snapshot_is_rejected_not_skipped_silently(profile):
    outcome = stage_2_momentum([candidate()], {}, profile, SimpleRvol(), AS_OF)

    assert not outcome.survivors
    assert outcome.rejections[0].stage == STAGE_2
    assert outcome.rejections[0].reason == "no market snapshot"


def test_missing_average_volume_rejects_rather_than_scoring_zero_rvol(profile):
    """Reference data can be stale or partial; a null must never read as 'low volume'."""
    outcome = run_stage_2(candidate(volume_avg_20d=None), 105.0, 250_000, profile)

    assert not outcome.survivors
    assert outcome.rejections[0].reason == "rvol unavailable"


def test_missing_prior_close_rejects_before_computing_a_gap(profile):
    outcome = run_stage_2(candidate(price_close_yesterday=None), 105.0, 250_000, profile)

    assert not outcome.survivors
    assert outcome.rejections[0].reason == "no prior close"


def test_stage_3_rejects_a_candidate_with_no_price(profile):
    outcome = stage_3_room_to_run([candidate()], profile)

    assert not outcome.survivors
    assert outcome.rejections[0].stage == STAGE_3
    assert outcome.rejections[0].reason == "no current price"


def test_normalized_rvol_fails_the_whole_scan_rather_than_every_ticker(profile):
    """If RVOL cannot be computed at all, that is an outage. Rejecting every ticker
    one by one would render as a quiet market — the exact confusion Phase 2 must avoid."""
    from app.services.scanner.errors import FeatureRequiresIntraday
    from app.services.scanner.rvol import NormalizedRvol

    with pytest.raises(FeatureRequiresIntraday):
        stage_2_momentum(
            [candidate()], snapshot(105.0, 250_000), profile, NormalizedRvol(), AS_OF
        )
