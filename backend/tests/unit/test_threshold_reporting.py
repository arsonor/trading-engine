"""Threshold reporting must always show EFFECTIVE values.

The bug this pins: `ThresholdProfile` carried a hardcoded `description` string naming the
designed float cap. `resolve_profile()` applies stored overrides with
`replace(profile, **applied)`, which updates the numbers and leaves that sentence alone —
so one run printed three lines that disagreed:

    Thresholds : float < 75,000,000                    <- effective
    WARNING ... float cap loosened to 20,000,000,000   <- nominal, stale
    Stage 1: 0/43 tickers passed (float < 75,000,000)  <- effective

"The system reports something false while behaving correctly" is the most expensive kind
of small bug: it sends you debugging the wrong thing. Every summary is now derived from
the fields at call time, and the parallel string is gone.
"""

from dataclasses import replace

import pytest

from app.services.scanner.profiles import ThresholdProfile, demo_profile, production_profile


def test_profile_has_no_stored_description_field():
    """The regression guard. A description that duplicates configuration is a second
    source of truth and will go stale again."""
    assert "description" not in ThresholdProfile.__dataclass_fields__


def test_threshold_summary_reflects_overridden_values():
    overridden = replace(demo_profile(), float_max=75_000_000)

    summary = overridden.threshold_summary()

    assert "75,000,000" in summary
    assert "20,000,000,000" not in summary


def test_describe_reflects_overridden_values():
    """This is the text that became stale — the demo warning line."""
    overridden = replace(demo_profile(), float_max=75_000_000)

    described = overridden.describe()

    assert "75,000,000" in described
    assert "20,000,000,000" not in described
    # Still says it is demo and still carries the caveat.
    assert "DEMO" in described
    assert "NOT actionable" in described


def test_every_summary_agrees_after_an_override():
    """The three lines that disagreed in the observed output must now agree."""
    overridden = replace(demo_profile(), float_max=1_234_567)

    rendered = " ".join(
        [
            overridden.threshold_summary(),
            overridden.risk_summary(),
            overridden.describe(),
            str(overridden.as_dict()),
        ]
    )

    assert "20,000,000,000" not in rendered
    assert rendered.count("1,234,567") >= 3


def test_as_dict_carries_the_derived_summary():
    """`as_dict` is stamped into scan_runs and alert payloads, so it must not embed a
    stale sentence either."""
    payload = replace(demo_profile(), float_max=42_000_000).as_dict()

    assert payload["float_max"] == 42_000_000
    assert "42,000,000" in payload["summary"]


@pytest.mark.parametrize("build", [production_profile, demo_profile])
def test_summaries_name_every_threshold(build):
    profile = build()
    combined = profile.threshold_summary() + profile.risk_summary()

    for value in (
        f"{profile.float_max:,}",
        f"{profile.avg_volume_min:,.0f}",
        str(profile.gap_min),
        str(profile.gap_max),
        str(profile.rvol_min),
        str(profile.upside_min),
        str(profile.price_floor),
    ):
        assert value in combined, value


def test_production_describe_does_not_claim_to_be_demo():
    described = production_profile().describe()

    assert "DEMO" not in described
    assert "Production" in described
