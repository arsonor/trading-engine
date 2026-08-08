"""Scan modes: what a run is permitted to write.

## The bug these pin

Phase 4C's two-stage go-live was specified as "full pipeline, `scan_runs` recorded, no
alerts persisted or broadcast". It was implemented by reusing `--dry-run`, which has meant
"touch nothing" since Phase 2. So the production cron performed a full live scan every five
minutes and threw the result away — `scan_runs` gained no rows for the entire observation
window, and there was nothing to decide thresholds from.

Nothing was broken in the scanner. A flag was reused for a purpose its name did not
describe, and no test asserted the difference because no test knew there was one.

These do.
"""

import pytest

from app.services.scanner.pipeline import (
    MODE_DRY_RUN,
    MODE_LIVE,
    MODE_OBSERVATION,
    describe_mode,
    resolve_mode,
)

# ------------------------------------------------------------------ resolution


def test_no_flags_is_live():
    assert resolve_mode(dry_run=False, no_alerts=False) == MODE_LIVE


def test_no_alerts_is_observation():
    assert resolve_mode(dry_run=False, no_alerts=True) == MODE_OBSERVATION


def test_dry_run_is_dry_run():
    assert resolve_mode(dry_run=True, no_alerts=False) == MODE_DRY_RUN


def test_dry_run_wins_when_both_are_given():
    """The stricter flag governs. Someone passing both means "write nothing" — resolving
    to observation would write a row they did not ask for."""
    assert resolve_mode(dry_run=True, no_alerts=True) == MODE_DRY_RUN


# ------------------------------------------------------------------ the descriptions

# The 4C bug was caught from a single log line. That is the quality worth keeping: each
# description states what WILL and WILL NOT be written, so a wrong mode is visible in the
# first few lines of output rather than three days later in an empty table.


@pytest.mark.parametrize("mode", [MODE_LIVE, MODE_OBSERVATION, MODE_DRY_RUN])
def test_every_mode_says_what_it_writes(mode):
    described = describe_mode(mode).lower()

    assert "written" in described
    assert "scan_runs" in described or "nothing" in described


def test_observation_is_explicit_that_the_run_is_recorded():
    """The precise thing the 4C implementation got wrong."""
    described = describe_mode(MODE_OBSERVATION)

    assert "scan_runs WILL be written" in described
    assert "alerts will NOT be" in described


def test_dry_run_is_explicit_that_nothing_is_written():
    assert "NOTHING will be written" in describe_mode(MODE_DRY_RUN)


def test_live_is_explicit_that_alerts_go_out():
    described = describe_mode(MODE_LIVE).lower()

    assert "alerts" in described
    assert "broadcast" in described


def test_an_unknown_mode_is_returned_rather_than_swallowed():
    """A mode read back from an old row must not render as an empty string."""
    assert describe_mode("something_else") == "something_else"
