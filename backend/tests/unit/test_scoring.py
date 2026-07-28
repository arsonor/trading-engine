"""Tests for confidence scoring.

Two themes. First, the arithmetic is transparent and the breakdown reconstructs the
score — if a user cannot verify the number from its parts, the "transparent weighted
formula" requirement is not met. Second, and more importantly, **a null `upside_pct`
must never break scoring**: Stage 3's rejection of breakout names is a deferred strategy
decision, and reversing it must stay a one-branch change.
"""

from datetime import datetime, timedelta

import pytest

from app.config import get_settings
from app.services.scanner.candidate import Candidate
from app.services.scanner.profiles import demo_profile, production_profile
from app.services.scanner.scoring import (
    FACTOR_DATA_QUALITY,
    FACTOR_GAP,
    FACTOR_LIQUIDITY,
    FACTOR_RVOL,
    FACTOR_UPSIDE,
    compute_confidence,
    suggested_entry_window,
)

AS_OF = datetime(2026, 7, 28, 9, 25)


def candidate(**overrides) -> Candidate:
    base = {
        "ticker": "TEST",
        "static_float": 40_000_000,
        "volume_avg_20d": 1_000_000.0,
        "price_close_yesterday": 100.0,
        "price_premarket_current": 105.0,
        "gap_pct": 5.0,
        "rvol_pct": 25.0,
        "rvol_is_approximate": False,
        "snapshot_source": "fmp-live",
        "nearest_resistance": 120.0,
        "resistance_source": "high_20d",
        "upside_pct": 14.29,
        "reference_computed_at": AS_OF,
    }
    base.update(overrides)
    return Candidate(**base)


def factor(score, name):
    return next(f for f in score.factors if f.name == name)


# ------------------------------------------------------------------ transparency


def test_score_is_the_sum_of_its_parts():
    """The breakdown must reconstruct the score, or it is decoration rather than proof."""
    score = compute_confidence(candidate(), production_profile(), AS_OF)

    total_weight = sum(f.weight for f in score.factors)
    reconstructed = sum(f.contribution for f in score.factors) / total_weight

    assert score.score == pytest.approx(reconstructed)


def test_every_factor_reports_its_arithmetic():
    score = compute_confidence(candidate(), production_profile(), AS_OF)

    assert {f.name for f in score.factors} == {
        FACTOR_GAP,
        FACTOR_RVOL,
        FACTOR_UPSIDE,
        FACTOR_LIQUIDITY,
        FACTOR_DATA_QUALITY,
    }
    for f in score.factors:
        assert 0.0 <= f.normalized <= 1.0
        assert f.contribution == pytest.approx(f.normalized * f.weight)
        assert f.detail


def test_score_is_always_marked_provisional():
    """Nothing has been backtested. The flag is part of the contract, not decoration."""
    score = compute_confidence(candidate(), production_profile(), AS_OF)

    assert score.is_provisional is True
    assert any("PROVISIONAL" in note for note in score.notes)


def test_score_stays_within_bounds():
    weak = candidate(gap_pct=14.9, rvol_pct=10.1, upside_pct=5.5, volume_avg_20d=5100.0)
    strong = candidate(gap_pct=6.0, rvol_pct=500.0, upside_pct=60.0, volume_avg_20d=50_000_000.0)

    for cand in (weak, strong):
        score = compute_confidence(cand, production_profile(), AS_OF)
        assert 0.0 <= score.score <= 1.0


# ------------------------------------------------------------------ null upside


def test_null_upside_does_not_crash_and_scores_neutrally():
    """The deferred-strategy-decision case. Neutral, not zero: unmeasured headroom is
    not bad headroom."""
    score = compute_confidence(
        candidate(upside_pct=None, nearest_resistance=None, resistance_source=None),
        production_profile(),
        AS_OF,
    )

    upside = factor(score, FACTOR_UPSIDE)
    assert upside.raw_value is None
    assert upside.normalized == get_settings().score_null_upside_fallback
    assert upside.is_fallback is True
    assert "unmeasured" in upside.detail
    assert 0.0 < score.score < 1.0


def test_null_upside_is_flagged_on_the_score_and_in_the_notes():
    score = compute_confidence(
        candidate(upside_pct=None, nearest_resistance=None), production_profile(), AS_OF
    )

    assert score.uses_fallback is True
    assert any("no resistance level above" in note for note in score.notes)


def test_null_upside_scores_between_the_worst_and_best_measured_cases():
    """The fallback must sit between a barely-qualifying upside and a great one —
    otherwise it silently buries or promotes every breakout name."""
    profile = production_profile()
    worst = compute_confidence(candidate(upside_pct=5.5), profile, AS_OF)
    best = compute_confidence(candidate(upside_pct=60.0), profile, AS_OF)
    unmeasured = compute_confidence(
        candidate(upside_pct=None, nearest_resistance=None), profile, AS_OF
    )

    assert factor(worst, FACTOR_UPSIDE).normalized < factor(unmeasured, FACTOR_UPSIDE).normalized
    assert factor(unmeasured, FACTOR_UPSIDE).normalized < factor(best, FACTOR_UPSIDE).normalized


def test_null_upside_also_costs_data_quality():
    """Leaning on a fallback is itself a reason to trust the score less."""
    profile = production_profile()
    measured = factor(compute_confidence(candidate(), profile, AS_OF), FACTOR_DATA_QUALITY)
    unmeasured = factor(
        compute_confidence(candidate(upside_pct=None), profile, AS_OF), FACTOR_DATA_QUALITY
    )

    assert unmeasured.normalized < measured.normalized


# ------------------------------------------------------------------ factor behaviour


def test_gap_near_the_ceiling_scores_below_a_gap_near_the_sweet_spot():
    """A 15% gap has spent most of the move it was screened for."""
    profile = production_profile()
    sweet = compute_confidence(candidate(gap_pct=6.0), profile, AS_OF)
    extended = compute_confidence(candidate(gap_pct=14.5), profile, AS_OF)

    assert factor(sweet, FACTOR_GAP).normalized > factor(extended, FACTOR_GAP).normalized


def test_rvol_just_over_the_threshold_adds_almost_no_conviction():
    score = compute_confidence(candidate(rvol_pct=10.1), production_profile(), AS_OF)

    assert factor(score, FACTOR_RVOL).normalized < 0.01


def test_rvol_saturates_rather_than_dominating():
    profile = production_profile()
    high = compute_confidence(candidate(rvol_pct=100.0), profile, AS_OF)
    absurd = compute_confidence(candidate(rvol_pct=100_000.0), profile, AS_OF)

    assert factor(high, FACTOR_RVOL).normalized == pytest.approx(1.0)
    assert factor(absurd, FACTOR_RVOL).normalized == pytest.approx(1.0)


def test_missing_rvol_scores_zero_and_is_flagged():
    score = compute_confidence(candidate(rvol_pct=None), production_profile(), AS_OF)

    rvol = factor(score, FACTOR_RVOL)
    assert rvol.normalized == 0.0
    assert rvol.is_fallback is True


# ------------------------------------------------------------------ data quality


def test_demo_profile_is_penalised():
    cand = candidate()
    production = factor(compute_confidence(cand, production_profile(), AS_OF), FACTOR_DATA_QUALITY)
    demo = factor(compute_confidence(cand, demo_profile(), AS_OF), FACTOR_DATA_QUALITY)

    assert demo.normalized < production.normalized
    assert "demo profile" in demo.detail


def test_approximate_rvol_is_penalised_and_noted():
    score = compute_confidence(
        candidate(rvol_is_approximate=True), production_profile(), AS_OF
    )

    assert "approximate RVOL" in factor(score, FACTOR_DATA_QUALITY).detail
    assert any("approximate" in note for note in score.notes)


def test_fixture_snapshots_are_penalised():
    """A confident-looking score built on constructed inputs is the worst thing this
    system could produce."""
    score = compute_confidence(
        candidate(snapshot_source="fixture"), production_profile(), AS_OF
    )

    assert "fixture snapshot" in factor(score, FACTOR_DATA_QUALITY).detail


def test_stale_reference_data_is_penalised():
    stale = candidate(reference_computed_at=AS_OF - timedelta(days=30))
    score = compute_confidence(stale, production_profile(), AS_OF)

    assert "days old" in factor(score, FACTOR_DATA_QUALITY).detail


def test_v1_reality_scores_data_quality_at_zero():
    """Demo + approximate RVOL + fixture snapshot is exactly what V1 produces, and it
    should bottom out the trust factor rather than quietly averaging out."""
    v1_candidate = candidate(rvol_is_approximate=True, snapshot_source="fixture")
    score = compute_confidence(v1_candidate, demo_profile(), AS_OF)

    assert factor(score, FACTOR_DATA_QUALITY).normalized == 0.0


def test_perfect_inputs_score_data_quality_at_one():
    score = compute_confidence(candidate(), production_profile(), AS_OF)

    quality = factor(score, FACTOR_DATA_QUALITY)
    assert quality.normalized == 1.0
    assert quality.detail == "all inputs nominal"


# ------------------------------------------------------------------ entry window


def test_final_pass_gets_a_concrete_entry_window():
    assert "09:30-10:00 ET" in suggested_entry_window(AS_OF, is_final_pass=True)


def test_early_pass_says_it_is_provisional():
    window = suggested_entry_window(datetime(2026, 7, 28, 5, 5), is_final_pass=False)

    assert "monitor" in window
    assert "09:25" in window


def test_serialisation_round_trips():
    score = compute_confidence(candidate(), production_profile(), AS_OF)
    payload = score.as_dict()

    assert payload["is_provisional"] is True
    assert len(payload["factors"]) == 5
    assert payload["score"] == pytest.approx(score.score, abs=1e-4)
