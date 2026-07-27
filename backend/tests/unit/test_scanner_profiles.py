"""Tests for threshold profiles.

Two things must hold. Thresholds come from settings, so the user can retune without a
redeploy. And demo output must be structurally impossible to mistake for production
output — the `is_demo` flag is what carries that warning into `scan_runs`, the alert
payload and the UI.
"""

import pytest

from app.config import Settings
from app.services.scanner.profiles import (
    DEMO,
    PRODUCTION,
    available_profiles,
    demo_profile,
    get_profile,
    production_profile,
)


def test_production_profile_matches_the_specification():
    """The values in docs/CLAUDE.md section 4.3."""
    profile = production_profile()

    assert profile.float_max == 75_000_000
    assert profile.avg_volume_min == 500_000
    assert profile.gap_min == 3.0
    assert profile.gap_max == 15.0
    assert profile.rvol_min == 10.0
    assert profile.upside_min == 5.5
    assert profile.price_floor == 2.0


def test_production_is_not_flagged_as_demo():
    assert production_profile().is_demo is False


def test_demo_loosens_only_the_float_cap():
    """The demo profile must exercise the SAME logic as production. If it relaxed the
    gap band or the upside bar too, a demo run would prove nothing about the real one."""
    production = production_profile()
    demo = demo_profile()

    assert demo.float_max > production.float_max
    for field in ("avg_volume_min", "gap_min", "gap_max", "rvol_min", "upside_min",
                  "price_floor", "dollar_volume_min"):
        assert getattr(demo, field) == getattr(production, field), field


def test_demo_is_flagged_and_describes_why():
    demo = demo_profile()

    assert demo.is_demo is True
    assert demo.name == DEMO
    assert "NOT actionable" in demo.description


def test_demo_float_cap_admits_the_free_tier_megacaps():
    """AAPL's real float is ~14.7B. Production rejects it; demo is what lets the
    pipeline be seen working on the only data V1 has."""
    assert production_profile().float_max < 14_700_000_000
    assert demo_profile().float_max > 14_700_000_000


def test_profile_dict_stamps_the_demo_flag_for_downstream_consumers():
    stamped = demo_profile().as_dict()

    assert stamped["name"] == DEMO
    assert stamped["is_demo"] is True
    assert stamped["float_max"] == demo_profile().float_max


def test_get_profile_resolves_by_name_case_insensitively():
    assert get_profile("production").name == PRODUCTION
    assert get_profile("DEMO").name == DEMO


def test_get_profile_rejects_unknown_names():
    with pytest.raises(ValueError, match="Unknown threshold profile"):
        get_profile("aggressive")


def test_available_profiles_lists_both():
    assert available_profiles() == [DEMO, PRODUCTION]


def test_thresholds_are_tunable_without_a_redeploy(monkeypatch):
    """The end user's strategy will evolve; retuning must be an env change, not a deploy."""
    from app.services.scanner import profiles

    tuned = Settings(
        database_url="postgresql+asyncpg://u:p@localhost:5432/db",
        scan_gap_min=2.0,
        scan_upside_min=8.0,
        scan_float_max=50_000_000,
    )
    monkeypatch.setattr(profiles, "get_settings", lambda: tuned)

    profile = production_profile()
    assert profile.gap_min == 2.0
    assert profile.upside_min == 8.0
    assert profile.float_max == 50_000_000
