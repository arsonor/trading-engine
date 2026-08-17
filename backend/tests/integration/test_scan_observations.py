"""Decision-time evidence for Phase 6.

The centrepiece is `test_a_threshold_sweep_is_answerable_from_stored_rows`. Phase 6 commits
to justifying or revising 3% / 15% / 10% / 5.5%, and before this table that question could
not be asked of stored data at all: rejections carried a reason and no numbers. If that
test ever stops passing, the commitment is broken again.

The second theme is that **NULL means not evaluated, never zero**. The stages short-circuit,
so a ticker rejected on gap has no RVOL, and a sweep that widens the gap band must report
such tickers as unresolved rather than quietly counting them as passing.
"""

from datetime import datetime

import pytest
from sqlalchemy import select

from app.models.scan_observation import ScanObservation
from app.models.scan_run import ScanRunStatus
from app.services.scanner.candidate import STAGE_2, STAGE_3, STAGE_RISK
from app.services.scanner.clock import FixedClock
from app.services.scanner.observations import (
    DEFAULT_ANCHOR_TIMES,
    ObservationRecorder,
    is_anchor_pass,
    should_record_all,
)
from app.services.scanner.pipeline import Scanner
from app.services.scanner.profiles import production_profile
from app.services.scanner.rvol import SimpleRvol

FINAL_PASS = datetime(2026, 7, 28, 9, 25)
ANCHOR = datetime(2026, 7, 28, 7, 0)
# An ordinary pass: not an anchor, but a minute the tiered cadence really scans. 06:00 —
# what this was — is inside the window and no longer a scheduled pass, so the run would be
# skipped and the test would prove nothing about recording.
ORDINARY = datetime(2026, 7, 28, 6, 15)


def build_scanner(session_factory, snapshots, at: datetime) -> Scanner:
    return Scanner(
        session_factory=session_factory,
        snapshot_provider=snapshots,
        profile=production_profile(),
        clock=FixedClock(at),
        rvol_calculator=SimpleRvol(),
    )


async def observations(session_factory) -> list[ScanObservation]:
    async with session_factory() as session:
        rows = await session.execute(
            select(ScanObservation).order_by(ScanObservation.ticker)
        )
        return list(rows.scalars().all())


# ------------------------------------------------------------------ the write policy


def test_only_the_final_pass_records_the_full_population():
    assert should_record_all(is_final_pass=True) is True
    assert should_record_all(is_final_pass=False) is False


def test_anchor_times_are_matched_at_minute_resolution():
    """Render starts a job 10-45 s late, so an anchor at 07:00 must match 07:00:23 —
    the same reason the scan window truncates before comparing."""
    assert is_anchor_pass(datetime(2026, 7, 28, 7, 0)) is True
    assert is_anchor_pass(datetime(2026, 7, 28, 7, 0, 23)) is True
    assert is_anchor_pass(datetime(2026, 7, 28, 7, 1)) is False
    assert is_anchor_pass(datetime(2026, 7, 28, 6, 0)) is False
    assert DEFAULT_ANCHOR_TIMES[0].isoformat() == "04:15:00", "the discovery pass"


# ------------------------------------------------------------------ what gets written


async def test_the_final_pass_records_every_stage_1_survivor(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """The rejected population is the whole point: a sweep asks about the tickers the
    scanner threw away, and counts alone cannot answer it."""
    scanner = build_scanner(test_session_factory, golden_snapshot_provider, FINAL_PASS)
    result = await scanner.run()

    rows = await observations(test_session_factory)

    assert result.counts.stage_1 == 7
    assert len(rows) == 7, "every Stage-1 survivor, not just the two candidates"
    assert result.observations_recorded == 7

    by_ticker = {row.ticker: row for row in rows}
    assert by_ticker["LOWF"].is_candidate is True
    assert by_ticker["LOWF"].stage_reached == STAGE_RISK
    assert by_ticker["LOWF"].rejection_reason is None

    assert by_ticker["SLOW"].is_candidate is False
    assert by_ticker["SLOW"].stage_reached == STAGE_2
    assert by_ticker["SLOW"].rejection_reason == "rvol too low"
    assert by_ticker["BRKO"].stage_reached == STAGE_3


async def test_a_rejected_ticker_keeps_the_numbers_that_rejected_it(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """The gap that failed the band is recorded. Storing only "gap outside band" is what
    made the sensitivity sweep impossible."""
    scanner = build_scanner(test_session_factory, golden_snapshot_provider, FINAL_PASS)
    await scanner.run()

    by_ticker = {row.ticker: row for row in await observations(test_session_factory)}

    assert by_ticker["FLAT"].gap_pct == 1.0
    assert by_ticker["BLOW"].gap_pct == 20.0
    # Rejected on gap, so RVOL was never computed. NOT zero — never evaluated.
    assert by_ticker["FLAT"].rvol_pct is None
    # Rejected on RVOL, so both numbers exist.
    assert by_ticker["SLOW"].gap_pct is not None
    assert by_ticker["SLOW"].rvol_pct == 10.0


async def test_the_denominators_are_copied_onto_the_row(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """`reference_data` is upserted nightly, so a join at read time would answer with
    tonight's numbers rather than the ones the decision was made from."""
    scanner = build_scanner(test_session_factory, golden_snapshot_provider, FINAL_PASS)
    await scanner.run()

    lowf = {row.ticker: row for row in await observations(test_session_factory)}["LOWF"]

    assert lowf.volume_avg_20d is not None
    assert lowf.price_close_yesterday == 100.0
    assert lowf.high_20d == 120.0
    assert lowf.static_float is not None
    assert lowf.session_date == FINAL_PASS.date()
    assert lowf.is_final_pass is True


async def test_an_anchor_pass_records_candidates_only(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    scanner = build_scanner(test_session_factory, golden_snapshot_provider, ANCHOR)
    result = await scanner.run()

    rows = await observations(test_session_factory)

    assert result.is_final_pass is False
    assert len(rows) == len(result.candidates)
    assert all(row.is_candidate for row in rows)
    assert all(row.is_final_pass is False for row in rows)


async def test_an_ordinary_pass_records_nothing(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """66 passes a session, near-duplicates of each other. Recording them all would be
    millions of rows a year for almost no information."""
    scanner = build_scanner(test_session_factory, golden_snapshot_provider, ORDINARY)
    result = await scanner.run()

    assert result.status == ScanRunStatus.COMPLETED
    assert await observations(test_session_factory) == []
    assert result.observations_recorded == 0


# ------------------------------------------------------------------ the sweep


async def test_a_threshold_sweep_is_answerable_from_stored_rows(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """THE test this table exists for.

    Recompute the Stage-2 survivor set at a different RVOL floor, using nothing but the
    stored observations — no re-fetching, no reference-data join, no live scan.
    """
    scanner = build_scanner(test_session_factory, golden_snapshot_provider, FINAL_PASS)
    result = await scanner.run()

    assert [c.ticker for c in result.candidates] == ["LOWF", "EDGE"]
    rows = await observations(test_session_factory)

    def stage_2_survivors_at(rvol_min: float, gap_min: float, gap_max: float):
        """Replay Stage 2's decision from stored values alone."""
        passing, unresolved = [], []
        for row in rows:
            if row.gap_pct is None:
                continue  # never reached Stage 2's gap test
            if not (gap_min <= row.gap_pct <= gap_max):
                continue
            if row.rvol_pct is None:
                # Admitted by the new gap band, but its RVOL was never computed because
                # the original run rejected it first. Unknown, NOT passing.
                unresolved.append(row.ticker)
                continue
            if row.rvol_pct > rvol_min:
                passing.append(row.ticker)
        return sorted(passing), sorted(unresolved)

    # 1. The live thresholds are reproduced exactly from storage.
    passing, unresolved = stage_2_survivors_at(rvol_min=10.0, gap_min=3.0, gap_max=15.0)
    assert unresolved == []
    assert set(passing) == {"LOWF", "EDGE", "BRKO", "NEAR"}, (
        "Stage 2's four survivors, recovered without touching the market"
    )

    # 2. Loosening the RVOL floor admits SLOW — the question Phase 6 needs to ask, and
    #    the one that was unanswerable before this table.
    passing, unresolved = stage_2_survivors_at(rvol_min=9.0, gap_min=3.0, gap_max=15.0)
    assert "SLOW" in passing
    assert unresolved == []

    # 3. Widening the gap band admits FLAT, whose RVOL was never computed. Reported as
    #    unresolved rather than silently counted as a survivor.
    passing, unresolved = stage_2_survivors_at(rvol_min=10.0, gap_min=0.5, gap_max=15.0)
    assert unresolved == ["FLAT"]
    assert "FLAT" not in passing


# ------------------------------------------------------------------ failure behaviour


async def test_a_failed_pass_records_nothing(
    test_session_factory, golden_reference_data
):
    """A failed pass has a partial population no decision was made from."""

    class BrokenProvider:
        source = "broken"

        async def get_snapshots(self, *_args, **_kwargs):
            raise RuntimeError("provider exploded")

    scanner = build_scanner(test_session_factory, BrokenProvider(), FINAL_PASS)
    result = await scanner.run()

    assert result.status == ScanRunStatus.FAILED
    assert await observations(test_session_factory) == []


async def test_a_recording_failure_never_fails_the_scan(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """A pass that cannot record its evidence still produced alerts. Failing it here
    would trade a live trading signal for a backtest row."""

    class ExplodingRecorder(ObservationRecorder):
        async def _record(self, *_args, **_kwargs):
            raise RuntimeError("disk on fire")

    scanner = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=production_profile(),
        clock=FixedClock(FINAL_PASS),
        rvol_calculator=SimpleRvol(),
        observation_recorder=ExplodingRecorder(test_session_factory),
    )

    result = await scanner.run()

    assert result.status == ScanRunStatus.COMPLETED
    assert [c.ticker for c in result.candidates] == ["LOWF", "EDGE"]
    assert result.observations_recorded == 0


async def test_recording_the_same_run_twice_converges(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """The unique constraint is on (scan_run_id, ticker); a retry must not duplicate."""
    scanner = build_scanner(test_session_factory, golden_snapshot_provider, FINAL_PASS)
    result = await scanner.run()

    recorder = ObservationRecorder(test_session_factory)
    written = await recorder.record(result, result.stage_1_survivors)

    assert written == 7
    assert len(await observations(test_session_factory)) == 7


async def test_a_dry_run_records_nothing(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    scanner = build_scanner(test_session_factory, golden_snapshot_provider, FINAL_PASS)
    result = await scanner.run(dry_run=True)

    assert result.scan_run_id is None
    assert await observations(test_session_factory) == []


@pytest.mark.parametrize("stage", [STAGE_2, STAGE_3, STAGE_RISK])
def test_every_stage_can_be_recorded_as_a_terminus(stage):
    """Guards the String(32) width against a stage identifier outgrowing it."""
    assert len(stage) <= 32
