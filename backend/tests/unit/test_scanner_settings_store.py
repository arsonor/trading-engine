"""Tests for runtime threshold overrides.

The requirement: threshold edits must survive a restart and apply to the next scan
without a redeploy. The safety requirement: an invalid combination must be rejected at
write time, because a gap band that matches nothing produces zero candidates forever and
looks exactly like a quiet market.
"""

import pytest

from app.services.scanner.settings_store import (
    InvalidThresholdOverrideError,
    ScannerSettingsStore,
    validate_overrides,
    validate_profile_name,
)


@pytest.fixture
def store(test_session_factory):
    return ScannerSettingsStore(session_factory=test_session_factory)


async def test_no_row_means_environment_defaults(store):
    profile_name, overrides = await store.get_overrides()

    assert profile_name is None
    assert overrides == {}

    profile = await store.resolve_profile()
    assert profile.name == "production"
    assert profile.gap_min == 3.0


async def test_saved_overrides_are_applied_to_the_profile(store):
    await store.save(overrides={"gap_min": 2.5, "upside_min": 8.0})
    profile = await store.resolve_profile()

    assert profile.gap_min == 2.5
    assert profile.upside_min == 8.0
    # Untouched thresholds still follow the environment.
    assert profile.gap_max == 15.0


async def test_only_pinned_keys_are_stored(store):
    await store.save(overrides={"gap_min": 2.5})
    _, overrides = await store.get_overrides()

    assert overrides == {"gap_min": 2.5}


async def test_stored_profile_is_used_when_no_explicit_choice(store):
    await store.save(profile="demo")

    assert (await store.resolve_profile()).name == "demo"


async def test_an_explicit_profile_beats_the_stored_one(store):
    """`--profile production` on the CLI must win over a saved preference."""
    await store.save(profile="demo")

    assert (await store.resolve_profile("production")).name == "production"


async def test_overrides_apply_across_profiles(store):
    await store.save(profile="demo", overrides={"gap_min": 4.0})

    demo = await store.resolve_profile("demo")
    production = await store.resolve_profile("production")

    assert demo.gap_min == 4.0
    assert production.gap_min == 4.0
    # The profile identity still differs where it should.
    assert demo.float_max > production.float_max


async def test_saving_twice_updates_the_same_row(store):
    await store.save(overrides={"gap_min": 2.5})
    await store.save(overrides={"gap_min": 4.0})

    _, overrides = await store.get_overrides()
    assert overrides == {"gap_min": 4.0}


async def test_clear_falls_back_to_the_environment(store):
    await store.save(profile="demo", overrides={"gap_min": 2.5})
    await store.clear()

    profile = await store.resolve_profile()
    assert profile.name == "production"
    assert profile.gap_min == 3.0


# ------------------------------------------------------------------ validation


def test_unknown_threshold_is_rejected():
    with pytest.raises(InvalidThresholdOverrideError, match="Unknown threshold"):
        validate_overrides({"moon_phase": 3})


def test_negative_threshold_is_rejected():
    with pytest.raises(InvalidThresholdOverrideError, match="cannot be negative"):
        validate_overrides({"gap_min": -1})


def test_non_numeric_threshold_is_rejected():
    with pytest.raises(InvalidThresholdOverrideError, match="must be a number"):
        validate_overrides({"gap_min": "soon"})


def test_inverted_gap_band_is_rejected_with_the_reason():
    """A band matching nothing would look like a quiet market, not a misconfiguration."""
    with pytest.raises(InvalidThresholdOverrideError, match="quiet market"):
        validate_overrides({"gap_min": 10.0, "gap_max": 5.0})


def test_float_max_is_coerced_to_an_integer():
    assert validate_overrides({"float_max": 75_000_000.0}) == {"float_max": 75_000_000}


def test_unknown_profile_is_rejected():
    with pytest.raises(InvalidThresholdOverrideError, match="Unknown profile"):
        validate_profile_name("aggressive")


def test_profile_name_is_normalised():
    assert validate_profile_name("  DEMO ") == "demo"


async def test_an_invalid_save_leaves_the_previous_settings_intact(store):
    await store.save(overrides={"gap_min": 2.5})

    with pytest.raises(InvalidThresholdOverrideError):
        await store.save(overrides={"gap_min": 20.0, "gap_max": 5.0})

    _, overrides = await store.get_overrides()
    assert overrides == {"gap_min": 2.5}
