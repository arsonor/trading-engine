"""Data-integrity guards.

Each guard exists because of a specific observed failure, not a general worry. The tests
name the observation so nobody later "simplifies" a guard away as speculative.

None of these reject a candidate; they observe and record. Suppression lives in
`risk.py`, where a rejection is a named, reported outcome rather than a silent drop —
see `tests/unit/test_risk_data_quality.py`.
"""

from app.services.scanner.candidate import Candidate
from app.services.scanner.integrity import (
    GUARD_PRICE_REGIME_BREAK,
    GUARD_VOLUME_DECREASED,
    GUARD_VOLUME_IMPLAUSIBLE,
    VolumeMonotonicityGuard,
    check_price_regime_break,
    check_volume_plausibility,
)


def candidate(ticker="TEST", close=100.0, avg_vol=1_000_000.0, high_20d=None) -> Candidate:
    return Candidate(
        ticker=ticker,
        price_close_yesterday=close,
        volume_avg_20d=avg_vol,
        high_20d=high_20d,
    )


# ------------------------------------------------------------------ monotonicity


def test_rising_volume_passes_through_untouched():
    guard = VolumeMonotonicityGuard()

    assert guard.check("AAPL", 1_000) == 1_000
    assert guard.check("AAPL", 5_000) == 5_000
    assert guard.findings == []


def test_a_decrease_keeps_the_high_water_mark_and_is_recorded():
    """The Tiingo probe watched a ticker's cumulative volume reset to zero mid-session and
    re-accumulate from a new baseline, permanently losing the earlier total. Acting on the
    lower number would understate RVOL for the rest of the morning."""
    guard = VolumeMonotonicityGuard()
    guard.check("PAVS", 3_060)

    kept = guard.check("PAVS", 0)

    assert kept == 3_060, "must not act on the lower figure"
    assert len(guard.findings) == 1
    assert guard.findings[0].guard == GUARD_VOLUME_DECREASED
    assert "cannot un-trade" in guard.findings[0].detail


def test_recovery_after_a_fault_does_not_re_trigger():
    guard = VolumeMonotonicityGuard()
    guard.check("PAVS", 3_060)
    guard.check("PAVS", 0)

    assert guard.check("PAVS", 4_000) == 4_000
    assert len(guard.findings) == 1


def test_tickers_are_tracked_independently():
    guard = VolumeMonotonicityGuard()
    guard.check("AAA", 5_000)

    assert guard.check("BBB", 10) == 10
    assert guard.findings == []


# ------------------------------------------------------------------ volume sanity


def test_ordinary_volume_is_not_flagged():
    assert check_volume_plausibility(candidate(), 2_000_000, multiple=50.0) is None


def test_absurd_volume_is_flagged_but_not_dropped():
    finding = check_volume_plausibility(candidate(), 60_000_000, multiple=50.0)

    assert finding is not None
    assert finding.guard == GUARD_VOLUME_IMPLAUSIBLE
    assert "60x" in finding.detail
    assert "not dropped" in finding.detail


def test_volume_sanity_needs_an_average_to_compare_against():
    assert check_volume_plausibility(candidate(avg_vol=None), 10_000_000) is None


# ------------------------------------------------------------------ price regime break

# This guard shipped in 4C as `split_distortion`, on the hypothesis that FMP served
# unadjusted history. Measurement disproved that: `historical-price-eod/full` IS split
# adjusted (FFAI's June bars come back at 42.42 / 97,942 volume against a raw tape of
# 0.2828 / 14,691,299 — both ratios exactly 150.0), and five of the seven flagged tickers
# had no split at all. What it detects is a real collapse. The tickers were right; the
# explanation was wrong.


def test_normal_reference_data_is_not_flagged():
    assert check_price_regime_break(candidate(close=100.0, high_20d=115.0)) is None


def test_a_collapsed_price_is_flagged():
    """FFAI, measured 7-8 August 2026: prior close 4.63 against a 20-day high of 32.17,
    having traded at 32.06 twenty sessions earlier. The data is correct — the stock fell
    86% — but its resistance levels describe a price regime it has left."""
    finding = check_price_regime_break(candidate("FFAI", close=4.63, high_20d=32.17))

    assert finding is not None
    assert finding.guard == GUARD_PRICE_REGIME_BREAK
    assert "6.9x" in finding.detail
    # The wording must NOT claim bad data; that hypothesis was measured and rejected.
    assert "unadjusted" not in finding.detail
    assert "data is correct" in finding.detail


def test_price_regime_guard_is_quiet_without_the_inputs():
    assert check_price_regime_break(candidate(close=None, high_20d=30.0)) is None
    assert check_price_regime_break(candidate(close=10.0, high_20d=None)) is None


def test_price_regime_threshold_is_a_parameter():
    """A volatile small cap can legitimately double in twenty sessions; the default of 3x
    is well clear of that, and the boundary is adjustable rather than assumed."""
    assert check_price_regime_break(candidate(close=10.0, high_20d=25.0), multiple=3.0) is None
    assert check_price_regime_break(candidate(close=10.0, high_20d=25.0), multiple=2.0) is not None
