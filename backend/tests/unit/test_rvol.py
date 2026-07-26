"""Tests for the pluggable RVOL calculators.

The point of this seam is that upgrading FMP tiers is a config change. These tests pin
both halves of that promise: `simple` works now and admits it is approximate, and
`normalized` refuses loudly rather than quietly degrading into `simple`.
"""

from datetime import datetime

import pytest

from app.services.scanner.errors import FeatureRequiresIntraday, InsufficientRvolData
from app.services.scanner.rvol import (
    MODE_NORMALIZED,
    MODE_SIMPLE,
    NormalizedRvol,
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


def test_normalized_rvol_requires_intraday_and_says_which_tier():
    with pytest.raises(FeatureRequiresIntraday) as exc_info:
        NormalizedRvol().compute(context())

    message = str(exc_info.value)
    assert "extended=true" in message
    assert "Premium" in message
    assert "RVOL_MODE=simple" in message


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
    assert isinstance(get_rvol_calculator("simple"), SimpleRvol)
    assert isinstance(get_rvol_calculator("NORMALIZED"), NormalizedRvol)


def test_factory_rejects_unknown_modes():
    with pytest.raises(ValueError, match="Unknown RVOL mode"):
        get_rvol_calculator("magic")


def test_factory_defaults_to_the_configured_mode():
    """V1 ships RVOL_MODE=simple; the default must not silently be the raising one."""
    assert get_rvol_calculator().mode == MODE_SIMPLE
