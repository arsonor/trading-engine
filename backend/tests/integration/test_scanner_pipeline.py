"""Full-pipeline integration tests.

The centrepiece is `test_golden_funnel_is_deterministic`, which runs the committed
`golden_session.json` scenario against the seeded `golden_reference_data` set and pins
every number in the funnel. If a threshold, a boundary convention or a resistance rule
changes, that test says exactly which one.

The other theme is the failure taxonomy: a scan that breaks, a scan that finds nothing,
and a scan that never ran must be three visibly different things — in `scan_runs` and,
from Phase 3, in the UI.
"""

from datetime import datetime

import pytest
from sqlalchemy import select

from app.models.scan_run import ScanRun, ScanRunStatus
from app.services.scanner.candidate import STAGE_2, STAGE_3, STAGE_RISK
from app.services.scanner.clock import FixedClock
from app.services.scanner.pipeline import (
    MODE_DRY_RUN,
    MODE_LIVE,
    MODE_OBSERVATION,
    Scanner,
)
from app.services.scanner.profiles import demo_profile, production_profile
from app.services.scanner.rvol import NormalizedRvol, SimpleRvol
from app.services.scanner.snapshot import FixtureSnapshotProvider

SCAN_AT = datetime(2026, 7, 28, 9, 25)  # the 09:25 ET final confirmation pass


@pytest.fixture
def scanner(test_session_factory, golden_snapshot_provider):
    return Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=production_profile(),
        clock=FixedClock(SCAN_AT),
        rvol_calculator=SimpleRvol(),
    )


# ------------------------------------------------------------------ the golden funnel


async def test_golden_funnel_is_deterministic(scanner, golden_reference_data):
    """The documented candidate set. Every figure below is hand-checkable against
    tests/fixtures/snapshots/golden_session.json and the conftest reference table."""
    result = await scanner.run()

    assert result.status == ScanRunStatus.COMPLETED
    assert result.counts.universe == 11
    # BIGF (float), THIN (avg volume), NOFL (null float) and PENN (price floor) are
    # filtered out in SQL before any snapshot is fetched.
    assert result.counts.stage_1 == 7
    # SLOW (rvol exactly 10.0), FLAT (gap 1%) and BLOW (gap 20%) die here.
    assert result.counts.stage_2 == 4
    # BRKO (above every level) and NEAR (2.86% upside) die here.
    assert result.counts.stage_3 == 2
    assert result.counts.risk_passed == 2

    assert [c.ticker for c in result.candidates] == ["LOWF", "EDGE"]


async def test_golden_candidate_values_are_exact(scanner, golden_reference_data):
    result = await scanner.run()
    lowf, edge = result.candidates

    assert lowf.gap_pct == 5.0
    assert lowf.rvol_pct == 25.0
    assert lowf.price_premarket_current == 105.0
    assert lowf.nearest_resistance == 120.0
    assert lowf.resistance_source == "high_20d"
    assert lowf.upside_pct == pytest.approx(14.285714, abs=1e-5)

    # EDGE sits on three boundaries at once and passes all three.
    assert edge.gap_pct == 3.0
    assert edge.rvol_pct == pytest.approx(10.0001)
    assert edge.upside_pct == 5.5


async def test_golden_rejections_name_the_stage_and_the_reason(scanner, golden_reference_data):
    result = await scanner.run()
    by_ticker = {r.ticker: r for r in result.rejections}

    assert by_ticker["SLOW"].stage == STAGE_2
    assert by_ticker["SLOW"].reason == "rvol too low"
    assert by_ticker["FLAT"].reason == "gap outside band"
    assert by_ticker["BLOW"].reason == "gap outside band"
    assert by_ticker["BRKO"].stage == STAGE_3
    assert by_ticker["BRKO"].reason == "no resistance above price"
    assert by_ticker["NEAR"].reason == "insufficient upside"


async def test_candidates_are_ranked_by_upside(scanner, golden_reference_data):
    result = await scanner.run()

    upsides = [c.upside_pct for c in result.candidates]
    assert upsides == sorted(upsides, reverse=True)


# ------------------------------------------------------------------ profiles


async def test_demo_profile_admits_tickers_production_rejects(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """BIGF's 900M float fails production Stage 1 and passes demo's loosened cap."""
    demo = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=demo_profile(),
        clock=FixedClock(SCAN_AT),
        rvol_calculator=SimpleRvol(),
    )

    result = await demo.run()

    assert result.counts.stage_1 == 8  # the production 7, plus BIGF
    assert "BIGF" in [c.ticker for c in result.candidates]


async def test_demo_runs_are_stamped_so_output_cannot_be_mistaken_for_real(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    demo = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=demo_profile(),
        clock=FixedClock(SCAN_AT),
        rvol_calculator=SimpleRvol(),
    )

    result = await demo.run()

    assert result.profile.is_demo is True
    assert result.summary()["is_demo"] is True

    async with test_session_factory() as session:
        run = await session.get(ScanRun, result.scan_run_id)
    assert run.profile == "demo"
    assert run.stage_counts_json["profile"]["is_demo"] is True


# ------------------------------------------------------------------ scan_runs audit


async def test_scan_run_records_a_complete_audit_trail(scanner, golden_reference_data):
    result = await scanner.run()

    async with scanner._session_factory() as session:
        run = await session.get(ScanRun, result.scan_run_id)

    assert run.status == ScanRunStatus.COMPLETED
    assert run.profile == "production"
    assert run.started_at is not None and run.finished_at is not None
    assert run.error is None

    counts = run.stage_counts_json["counts"]
    assert counts["universe"] == 11
    assert counts["stage_1_liquidity"] == 7
    assert counts["stage_2_momentum"] == 4
    assert counts["stage_3_room_to_run"] == 2

    assert run.stage_counts_json["candidates"] == ["LOWF", "EDGE"]
    assert run.stage_counts_json["is_final_pass"] is True
    assert run.stage_counts_json["rvol_mode"] == "simple"
    assert run.stage_counts_json["snapshot_source"] == "fixture"
    assert len(run.stage_counts_json["rejections"]) == 5


async def test_dry_run_writes_no_scan_run(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    scanner = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=production_profile(),
        clock=FixedClock(SCAN_AT),
        rvol_calculator=SimpleRvol(),
    )

    result = await scanner.run(dry_run=True)

    assert result.candidates  # the scan still ran
    assert result.scan_run_id is None
    async with test_session_factory() as session:
        assert (await session.execute(select(ScanRun))).scalars().all() == []


# ------------------------------------------------------------------ failure taxonomy


async def test_zero_candidates_is_a_success_not_a_failure(
    test_session_factory, golden_reference_data
):
    """The single most important distinction in this phase: a quiet market and a broken
    scanner must never render the same way."""
    empty = FixtureSnapshotProvider(scenario={"snapshots": {}})
    scanner = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=empty,
        profile=production_profile(),
        clock=FixedClock(SCAN_AT),
        rvol_calculator=SimpleRvol(),
    )

    result = await scanner.run()

    assert result.status == ScanRunStatus.COMPLETED
    assert result.succeeded is True
    assert result.is_quiet_market is True
    assert result.error is None

    async with test_session_factory() as session:
        run = await session.get(ScanRun, result.scan_run_id)
    assert run.status == ScanRunStatus.COMPLETED
    assert run.error is None


async def test_a_broken_scan_is_recorded_as_failed_with_the_reason(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """RVOL_MODE=normalized on the free tier cannot compute anything. Rejecting every
    ticker would look like a quiet market; the run must fail instead."""
    scanner = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=production_profile(),
        clock=FixedClock(SCAN_AT),
        rvol_calculator=NormalizedRvol(),
    )

    result = await scanner.run()

    assert result.status == ScanRunStatus.FAILED
    assert result.succeeded is False
    assert result.is_quiet_market is False
    assert "FeatureRequiresIntraday" in result.error
    assert "Premium" in result.error

    async with test_session_factory() as session:
        run = await session.get(ScanRun, result.scan_run_id)
    assert run.status == ScanRunStatus.FAILED
    assert run.error and run.finished_at is not None


async def test_a_run_row_exists_before_the_work_starts(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """A process killed mid-scan leaves a `running` row — which is the only way to tell
    'died silently' from 'never started'."""
    scanner = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=production_profile(),
        clock=FixedClock(SCAN_AT),
        rvol_calculator=SimpleRvol(),
    )

    run_id = await scanner._open_run(
        type("R", (), {"as_of_et": SCAN_AT, "is_final_pass": True, "mode": MODE_LIVE})()
    )

    async with test_session_factory() as session:
        run = await session.get(ScanRun, run_id)
    assert run.status == ScanRunStatus.RUNNING
    assert run.finished_at is None
    # The mode is on the row from the moment it opens: a run that dies mid-flight still
    # has to say what it was permitted to write.
    assert run.mode == MODE_LIVE


async def test_missing_snapshot_provider_fails_loudly(
    test_session_factory, golden_reference_data
):
    scanner = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=None,
        profile=production_profile(),
        clock=FixedClock(SCAN_AT),
        rvol_calculator=SimpleRvol(),
    )

    result = await scanner.run()

    assert result.status == ScanRunStatus.FAILED
    assert "--fixture" in result.error


# ------------------------------------------------------------------ window gating


async def test_a_scan_outside_the_window_is_skipped_not_run(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """The cron fires generously in UTC; the ET gate is what stops it working at 15:00."""
    scanner = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=production_profile(),
        clock=FixedClock(datetime(2026, 7, 28, 15, 0)),
        rvol_calculator=SimpleRvol(),
    )

    result = await scanner.run()

    assert result.status == ScanRunStatus.SKIPPED
    assert result.candidates == []
    assert "outside the 04:00-09:25 ET scan window" in result.error
    # No row: an out-of-window wake-up is noise, not an audit event.
    async with test_session_factory() as session:
        assert (await session.execute(select(ScanRun))).scalars().all() == []


async def test_ignore_window_allows_manual_runs_at_any_hour(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    scanner = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=production_profile(),
        clock=FixedClock(datetime(2026, 7, 28, 15, 0)),
        rvol_calculator=SimpleRvol(),
    )

    result = await scanner.run(ignore_window=True)

    assert result.status == ScanRunStatus.COMPLETED
    assert [c.ticker for c in result.candidates] == ["LOWF", "EDGE"]


async def test_only_the_0925_pass_is_marked_final(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    def scanner_at(moment):
        return Scanner(
            session_factory=test_session_factory,
            snapshot_provider=golden_snapshot_provider,
            profile=production_profile(),
            clock=FixedClock(moment),
            rvol_calculator=SimpleRvol(),
        )

    early = await scanner_at(datetime(2026, 7, 28, 8, 45)).run()
    final = await scanner_at(datetime(2026, 7, 28, 9, 25)).run()

    assert early.is_final_pass is False
    assert final.is_final_pass is True
    # Stage 3 is still evaluated early — the upside figure is useful before 09:25.
    assert early.counts.stage_3 == final.counts.stage_3


# ------------------------------------------------------------------ misconfiguration


async def test_demo_with_zero_stage_1_survivors_reports_misconfiguration(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """Demo exists so the free-tier universe DOES clear Stage 1. Zero survivors means
    the thresholds are wrong — most often a stored override reverting the loosened float
    cap — and reporting that as a quiet market sends the operator to look at the market
    instead of at their settings."""
    from dataclasses import replace as dc_replace

    # Demo, but with the float cap reverted to production's — exactly what a stored
    # override used to do silently.
    broken = dc_replace(demo_profile(), float_max=1)
    scanner = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=broken,
        clock=FixedClock(SCAN_AT),
        rvol_calculator=SimpleRvol(),
    )

    result = await scanner.run()

    assert result.status == ScanRunStatus.COMPLETED
    assert result.counts.universe > 0
    assert result.counts.stage_1 == 0
    assert result.candidates == []

    # The whole point: NOT a quiet market.
    assert result.is_quiet_market is False
    assert result.misconfiguration is not None
    assert "misconfiguration" in result.misconfiguration.lower()
    # It must point at the effective thresholds so the operator can see the culprit.
    assert "float < 1" in result.misconfiguration
    assert "settings" in result.misconfiguration.lower()

    async with test_session_factory() as session:
        run = await session.get(ScanRun, result.scan_run_id)
    assert run.stage_counts_json["misconfiguration"]


async def test_production_with_zero_stage_1_survivors_is_a_quiet_market(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """The same funnel shape in PRODUCTION is expected on the free tier — every symbol
    genuinely fails the real float cap. It must not be flagged as a misconfiguration."""
    from dataclasses import replace as dc_replace

    strict = dc_replace(production_profile(), float_max=1)
    scanner = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=strict,
        clock=FixedClock(SCAN_AT),
        rvol_calculator=SimpleRvol(),
    )

    result = await scanner.run()

    assert result.counts.stage_1 == 0
    assert result.misconfiguration is None
    assert result.is_quiet_market is True


async def test_demo_with_survivors_reports_no_misconfiguration(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    demo = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=demo_profile(),
        clock=FixedClock(SCAN_AT),
        rvol_calculator=SimpleRvol(),
    )

    result = await demo.run()

    assert result.counts.stage_1 > 0
    assert result.misconfiguration is None


# ------------------------------------------------------------------ scoping


async def test_tickers_argument_scopes_the_scan(scanner, golden_reference_data):
    result = await scanner.run(tickers=["LOWF"])

    assert result.counts.universe == 1
    assert [c.ticker for c in result.candidates] == ["LOWF"]


async def test_risk_filter_vetoes_a_thin_name(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    """A candidate can clear all three stages and still be blocked as untradeable."""
    from app.services.scanner.profiles import production_profile as build

    strict = build()
    strict = type(strict)(**{**strict.__dict__, "dollar_volume_min": 500_000_000.0})
    scanner = Scanner(
        session_factory=test_session_factory,
        snapshot_provider=golden_snapshot_provider,
        profile=strict,
        clock=FixedClock(SCAN_AT),
        rvol_calculator=SimpleRvol(),
    )

    result = await scanner.run()

    assert result.counts.stage_3 == 2
    assert result.counts.risk_passed == 0
    assert result.rejections_at(STAGE_RISK)[0].reason == "insufficient dollar volume"


# ===================================================== scan modes (post-4C hotfix)


async def test_observation_mode_writes_the_run_but_no_alerts(scanner, golden_reference_data):
    """THE regression test for the Phase 4C flag conflation.

    `--dry-run` was reused to mean "record the scan but skip alerts". It does not — it has
    meant "touch nothing" since Phase 2 — so the production cron discarded every scan for
    the whole observation window and `scan_runs` gained no rows to decide thresholds from.
    """
    result = await scanner.run(no_alerts=True)

    assert result.mode == MODE_OBSERVATION
    assert result.scan_run_id is not None, "the run MUST be recorded in observation mode"


async def test_dry_run_still_writes_nothing(scanner, golden_reference_data):
    """`--dry-run` keeps its original meaning. It is used for local testing and must not
    be redefined by this hotfix."""
    result = await scanner.run(dry_run=True)

    assert result.mode == MODE_DRY_RUN
    assert result.scan_run_id is None


async def test_dry_run_wins_when_both_flags_are_given(scanner, golden_reference_data):
    """The stricter flag governs — resolving to observation would write a row the caller
    explicitly asked not to write."""
    result = await scanner.run(dry_run=True, no_alerts=True)

    assert result.mode == MODE_DRY_RUN
    assert result.scan_run_id is None


async def test_a_default_run_is_live(scanner, golden_reference_data):
    result = await scanner.run()

    assert result.mode == MODE_LIVE
    assert result.scan_run_id is not None
