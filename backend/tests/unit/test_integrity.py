"""Data-integrity guards.

Each guard exists because of a specific observed failure, not a general worry. The tests
name the observation so nobody later "simplifies" a guard away as speculative.

None of these reject a candidate. They observe and record — the scanner's job is to
surface opportunities, and a guard that silently swallowed a real 30x morning would be a
worse bug than the one it prevents.
"""

from app.services.scanner.candidate import Candidate
from app.services.scanner.integrity import (
    GUARD_SPLIT_DISTORTION,
    GUARD_VOLUME_DECREASED,
    GUARD_VOLUME_IMPLAUSIBLE,
    VolumeMonotonicityGuard,
    check_split_distortion,
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


# ------------------------------------------------------------------ split distortion


def test_normal_reference_data_is_not_flagged():
    assert check_split_distortion(candidate(close=100.0, high_20d=115.0)) is None


def test_unadjusted_split_history_is_flagged():
    """Measured on FFAI, 7 August 2026: prior close 4.63, 20-day high 32.17, SMA-200 94.32.

    Twenty sessions cannot produce a 7x spread. The history is unadjusted across a reverse
    split, which makes every resistance level — and the `upside_pct` shown to the user —
    fiction. Unflagged, this reads as the single best opportunity on the list.
    """
    finding = check_split_distortion(candidate("FFAI", close=4.63, high_20d=32.17))

    assert finding is not None
    assert finding.guard == GUARD_SPLIT_DISTORTION
    assert "6.9x" in finding.detail
    assert "unadjusted" in finding.detail


def test_split_guard_is_quiet_without_the_inputs():
    assert check_split_distortion(candidate(close=None, high_20d=30.0)) is None
    assert check_split_distortion(candidate(close=10.0, high_20d=None)) is None


def test_split_guard_threshold_is_a_parameter():
    """A volatile small cap can legitimately double in twenty sessions; the default of 3x
    is well clear of that, and the boundary is adjustable rather than assumed."""
    assert check_split_distortion(candidate(close=10.0, high_20d=25.0), multiple=3.0) is None
    assert check_split_distortion(candidate(close=10.0, high_20d=25.0), multiple=2.0) is not None
