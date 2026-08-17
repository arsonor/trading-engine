"""Integration tests for alert persistence, dedup and broadcast.

Dedup is the behaviour that matters most here. Scans run every 5 minutes for five and a
half hours, so without it a ticker that qualifies all morning produces ~66 alerts. The
user must see a short list that evolves, not a feed that repeats.
"""

from datetime import datetime

import pytest
from sqlalchemy import func, select

from app.models.alert import Alert
from app.services.alerts import ScannerAlertService
from app.services.scanner.clock import FixedClock
from app.services.scanner.pipeline import Scanner
from app.services.scanner.profiles import demo_profile, production_profile
from app.services.scanner.rvol import NormalizedRvol, SimpleRvol

SCAN_AT = datetime(2026, 7, 28, 9, 25)
# An early pass that the tiered cadence actually runs. 05:05 — what this was — is inside
# the window but off-cadence since Follow-up A, so the scan would be skipped and the
# dedup-across-passes assertions would have had nothing to dedup.
EARLIER = datetime(2026, 7, 28, 5, 15)


class RecordingBroadcaster:
    """Captures broadcasts instead of pushing them to sockets."""

    def __init__(self):
        self.messages = []

    async def broadcast_to_channel(self, channel, message):
        self.messages.append((channel, message))


@pytest.fixture
def broadcaster():
    return RecordingBroadcaster()


@pytest.fixture
def service(test_session_factory, broadcaster):
    return ScannerAlertService(session_factory=test_session_factory, broadcaster=broadcaster)


def build_scanner(test_session_factory, provider, moment=SCAN_AT, profile=None, rvol=None):
    return Scanner(
        session_factory=test_session_factory,
        snapshot_provider=provider,
        profile=profile or production_profile(),
        clock=FixedClock(moment),
        rvol_calculator=rvol or SimpleRvol(),
    )


async def run_and_persist(test_session_factory, provider, service, **kwargs):
    result = await build_scanner(test_session_factory, provider, **kwargs).run()
    report = await service.persist_scan_result(result)
    return result, report


# ------------------------------------------------------------------ persistence


async def test_scan_persists_alerts_with_the_full_v2_contract(
    test_session_factory, golden_snapshot_provider, golden_reference_data, service
):
    _, report = await run_and_persist(test_session_factory, golden_snapshot_provider, service)

    assert sorted(report.created) == ["EDGE", "LOWF"]

    async with test_session_factory() as session:
        alert = await session.scalar(select(Alert).where(Alert.ticker == "LOWF"))

    assert alert.session_date == SCAN_AT.date()
    assert alert.gap_pct == 5.0
    assert alert.rvol_pct == 25.0
    assert alert.entry_reference_price == 105.0
    assert alert.nearest_resistance == 120.0
    assert alert.resistance_source == "high_20d"
    assert alert.upside_pct == pytest.approx(14.285714, abs=1e-5)
    assert alert.profile == "production"
    assert alert.is_final_pass is True
    assert alert.suggested_entry_window
    assert 0 <= alert.confidence_score <= 1
    assert alert.scan_run_id is not None
    # Catalyst tagging is Phase 4 — the field exists and is honestly empty.
    assert alert.catalyst is None


async def test_persisted_alert_carries_the_score_breakdown(
    test_session_factory, golden_snapshot_provider, golden_reference_data, service
):
    await run_and_persist(test_session_factory, golden_snapshot_provider, service)

    async with test_session_factory() as session:
        alert = await session.scalar(select(Alert).where(Alert.ticker == "LOWF"))

    breakdown = alert.score_breakdown_json
    assert breakdown["is_provisional"] is True
    assert len(breakdown["factors"]) == 5
    assert breakdown["score"] == pytest.approx(alert.confidence_score, abs=1e-3)


async def test_alerts_are_ordered_by_confidence(
    test_session_factory, golden_snapshot_provider, golden_reference_data, service
):
    await run_and_persist(test_session_factory, golden_snapshot_provider, service)

    alerts = await service.session_alerts(SCAN_AT.date())
    scores = [a.confidence_score for a in alerts]

    assert scores == sorted(scores, reverse=True)


# ------------------------------------------------------------------ dedup


async def test_a_second_scan_updates_in_place_rather_than_duplicating(
    test_session_factory, golden_snapshot_provider, golden_reference_data, service
):
    """~66 scans a session must not become ~66 alerts per ticker."""
    _, first = await run_and_persist(
        test_session_factory, golden_snapshot_provider, service, moment=EARLIER
    )
    _, second = await run_and_persist(test_session_factory, golden_snapshot_provider, service)

    assert len(first.created) == 2
    assert first.updated == []
    assert second.created == []
    assert sorted(second.updated) == ["EDGE", "LOWF"]

    async with test_session_factory() as session:
        total = await session.scalar(
            select(func.count(Alert.id)).where(Alert.session_date == SCAN_AT.date())
        )
    assert total == 2


async def test_the_later_scan_wins_on_conflicting_values(
    test_session_factory, golden_snapshot_provider, golden_reference_data, service
):
    """The 09:25 confirmation pass must overwrite the 05:05 provisional picture."""
    await run_and_persist(
        test_session_factory, golden_snapshot_provider, service, moment=EARLIER
    )

    async with test_session_factory() as session:
        early = await session.scalar(select(Alert).where(Alert.ticker == "LOWF"))
        assert early.is_final_pass is False
        assert "monitor" in early.suggested_entry_window

    await run_and_persist(test_session_factory, golden_snapshot_provider, service)

    async with test_session_factory() as session:
        final = await session.scalar(select(Alert).where(Alert.ticker == "LOWF"))

    assert final.is_final_pass is True
    assert "09:30-10:00 ET" in final.suggested_entry_window


async def test_a_re_alert_resurfaces_as_unread(
    test_session_factory, golden_snapshot_provider, golden_reference_data, service
):
    await run_and_persist(
        test_session_factory, golden_snapshot_provider, service, moment=EARLIER
    )

    async with test_session_factory() as session:
        alert = await session.scalar(select(Alert).where(Alert.ticker == "LOWF"))
        alert.is_read = True
        await session.commit()

    await run_and_persist(test_session_factory, golden_snapshot_provider, service)

    async with test_session_factory() as session:
        alert = await session.scalar(select(Alert).where(Alert.ticker == "LOWF"))
    assert alert.is_read is False


async def test_different_sessions_get_separate_alerts(
    test_session_factory, golden_snapshot_provider, golden_reference_data, service
):
    await run_and_persist(test_session_factory, golden_snapshot_provider, service)
    await run_and_persist(
        test_session_factory,
        golden_snapshot_provider,
        service,
        moment=datetime(2026, 7, 29, 9, 25),
    )

    async with test_session_factory() as session:
        total = await session.scalar(
            select(func.count(Alert.id)).where(Alert.ticker == "LOWF")
        )
    assert total == 2


# ------------------------------------------------------------------ failure handling


async def test_a_failed_scan_persists_nothing(
    test_session_factory, golden_snapshot_provider, golden_reference_data, service
):
    """A failed run's partial list is not a result. Writing it would let an outage
    masquerade as a thin session."""
    result = await build_scanner(
        test_session_factory, golden_snapshot_provider, rvol=NormalizedRvol()
    ).run()
    report = await service.persist_scan_result(result)

    assert result.succeeded is False
    assert report.total == 0

    async with test_session_factory() as session:
        assert (await session.execute(select(Alert))).scalars().all() == []


async def test_a_quiet_market_persists_nothing_but_is_not_a_failure(
    test_session_factory, golden_reference_data, service
):
    from app.services.scanner.snapshot import FixtureSnapshotProvider

    empty = FixtureSnapshotProvider(scenario={"snapshots": {}})
    result, report = await run_and_persist(test_session_factory, empty, service)

    assert result.succeeded is True
    assert report.total == 0


# ------------------------------------------------------------------ broadcast


async def test_alerts_are_broadcast_on_the_existing_channel(
    test_session_factory, golden_snapshot_provider, golden_reference_data, service, broadcaster
):
    """The transport is unchanged — only the payload is extended."""
    await run_and_persist(test_session_factory, golden_snapshot_provider, service)

    assert len(broadcaster.messages) == 1
    channel, message = broadcaster.messages[0]

    assert channel == "alerts"
    assert message["type"] == "scan_alerts"
    assert message["data"]["session_date"] == "2026-07-28"
    assert len(message["data"]["alerts"]) == 2
    assert message["data"]["alerts"][0]["ticker"] in {"LOWF", "EDGE"}


async def test_broadcast_payload_carries_the_demo_flag(
    test_session_factory, golden_snapshot_provider, golden_reference_data, service, broadcaster
):
    await run_and_persist(
        test_session_factory, golden_snapshot_provider, service, profile=demo_profile()
    )

    _, message = broadcaster.messages[0]
    assert message["data"]["is_demo"] is True
    assert all(alert["is_demo"] for alert in message["data"]["alerts"])


async def test_a_zero_candidate_scan_still_broadcasts(
    test_session_factory, golden_reference_data, service, broadcaster
):
    """A successful scan that finds nothing must still push, or a dashboard showing an
    earlier failure stays stuck on 'SCANNER FAILING' until the next status poll. The
    failure-to-healthy transition is the most important one to deliver promptly."""
    from app.services.scanner.snapshot import FixtureSnapshotProvider

    empty = FixtureSnapshotProvider(scenario={"snapshots": {}})
    result, report = await run_and_persist(test_session_factory, empty, service)

    assert result.succeeded is True
    assert report.total == 0
    assert len(broadcaster.messages) == 1

    _, message = broadcaster.messages[0]
    assert message["type"] == "scan_alerts"
    assert message["data"]["alerts"] == []
    assert message["data"]["scan_run_id"] == result.scan_run_id


async def test_broadcast_carries_the_whole_session_not_just_this_scans_candidates(
    test_session_factory, golden_snapshot_provider, golden_reference_data, service, broadcaster
):
    """A client that missed an earlier push must converge on the right list."""
    await run_and_persist(test_session_factory, golden_snapshot_provider, service)
    broadcaster.messages.clear()

    # A later scan of a single ticker still broadcasts both session alerts.
    result = await build_scanner(test_session_factory, golden_snapshot_provider).run(
        tickers=["LOWF"]
    )
    await service.persist_scan_result(result)

    _, message = broadcaster.messages[0]
    assert {a["ticker"] for a in message["data"]["alerts"]} == {"LOWF", "EDGE"}


async def test_a_failed_scan_does_not_broadcast(
    test_session_factory, golden_snapshot_provider, golden_reference_data, service, broadcaster
):
    """A failure must not push an alert list that would look like a fresh healthy scan."""
    result = await build_scanner(
        test_session_factory, golden_snapshot_provider, rvol=NormalizedRvol()
    ).run()
    await service.persist_scan_result(result)

    assert broadcaster.messages == []


async def test_a_broadcast_failure_does_not_lose_the_persisted_alerts(
    test_session_factory, golden_snapshot_provider, golden_reference_data
):
    class BrokenBroadcaster:
        async def broadcast_to_channel(self, channel, message):
            raise RuntimeError("socket gone")

    service = ScannerAlertService(
        session_factory=test_session_factory, broadcaster=BrokenBroadcaster()
    )
    _, report = await run_and_persist(test_session_factory, golden_snapshot_provider, service)

    assert report.total == 2
    assert report.broadcast == 0
    async with test_session_factory() as session:
        assert len((await session.execute(select(Alert))).scalars().all()) == 2
