"""Tests for the scanner API.

The `/status` endpoint gets the most attention: it is the endpoint that carries the
quiet-market-vs-outage distinction into the UI, and a client that cannot tell them apart
will eventually trust neither.
"""

from datetime import date, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.models.alert import Alert
from app.models.scan_run import ScanRun, ScanRunStatus

SESSION = date(2026, 7, 28)


@pytest.fixture
async def scanner_alert(db_session):
    run = ScanRun(
        started_at=datetime(2026, 7, 28, 13, 25),
        finished_at=datetime(2026, 7, 28, 13, 25, 1),
        status=ScanRunStatus.COMPLETED,
        profile="production",
        stage_counts_json={"counts": {"universe": 11, "stage_1_liquidity": 7}},
    )
    db_session.add(run)
    await db_session.commit()
    await db_session.refresh(run)

    alert = Alert(
        ticker="LOWF",
        session_date=SESSION,
        timestamp=datetime(2026, 7, 28, 13, 25),
        scan_timestamp=datetime(2026, 7, 28, 13, 25),
        scan_run_id=run.id,
        profile="production",
        gap_pct=5.0,
        rvol_pct=25.0,
        rvol_mode="simple",
        rvol_is_approximate=True,
        entry_reference_price=105.0,
        nearest_resistance=120.0,
        resistance_source="high_20d",
        upside_pct=14.29,
        suggested_entry_window="09:30-10:00 ET",
        confidence_score=0.62,
        is_final_pass=True,
        score_breakdown_json={
            "score": 0.62,
            "is_provisional": True,
            "profile": "production",
            "uses_fallback": False,
            "factors": [
                {
                    "name": "rvol",
                    "raw_value": 25.0,
                    "normalized": 0.17,
                    "weight": 0.3,
                    "contribution": 0.05,
                    "detail": "RVOL 25.0%",
                    "is_fallback": False,
                }
            ],
            "notes": ["PROVISIONAL"],
        },
    )
    db_session.add(alert)
    await db_session.commit()
    await db_session.refresh(alert)
    return alert


# ------------------------------------------------------------------ alerts


async def test_list_alerts_returns_the_v2_contract(client: AsyncClient, scanner_alert):
    response = await client.get("/api/v1/scanner/alerts")
    assert response.status_code == 200

    body = response.json()
    assert body["session_date"] == "2026-07-28"
    assert body["total"] == 1

    item = body["items"][0]
    # Storage and contract now agree on `ticker`; the mapping layer is gone.
    assert item["ticker"] == "LOWF"
    assert "symbol" not in item
    assert item["gap_pct"] == 5.0
    assert item["upside_pct"] == 14.29
    assert item["rvol_is_approximate"] is True
    assert item["suggested_entry_window"] == "09:30-10:00 ET"
    assert item["catalyst"] is None


async def test_alert_carries_the_score_breakdown(client: AsyncClient, scanner_alert):
    response = await client.get(f"/api/v1/scanner/alerts/{scanner_alert.id}")

    breakdown = response.json()["score_breakdown"]
    assert breakdown["is_provisional"] is True
    assert breakdown["factors"][0]["name"] == "rvol"


async def test_empty_state_is_not_an_error(client: AsyncClient):
    """No alerts is a valid, frequent outcome — never a 404."""
    response = await client.get("/api/v1/scanner/alerts")

    assert response.status_code == 200
    assert response.json() == {
        "items": [],
        "total": 0,
        "session_date": None,
        "has_demo_alerts": False,
    }


async def test_demo_alerts_are_flagged_on_the_list(client: AsyncClient, db_session):
    db_session.add(
        Alert(
            ticker="ADBE",
            session_date=SESSION,
            timestamp=datetime(2026, 7, 28, 13, 25),
            profile="demo",
            confidence_score=0.5,
        )
    )
    await db_session.commit()

    body = (await client.get("/api/v1/scanner/alerts")).json()
    assert body["has_demo_alerts"] is True
    assert body["items"][0]["is_demo"] is True


async def test_null_upside_serialises_as_null_not_zero(client: AsyncClient, db_session):
    """The breakout case must survive the API boundary intact."""
    db_session.add(
        Alert(
            ticker="BRKO",
            session_date=SESSION,
            timestamp=datetime(2026, 7, 28, 13, 25),
            profile="production",
            gap_pct=5.0,
            upside_pct=None,
            nearest_resistance=None,
            confidence_score=0.4,
        )
    )
    await db_session.commit()

    item = (await client.get("/api/v1/scanner/alerts")).json()["items"][0]
    assert item["upside_pct"] is None
    assert item["nearest_resistance"] is None


async def test_mark_alert_read(client: AsyncClient, scanner_alert):
    response = await client.post(f"/api/v1/scanner/alerts/{scanner_alert.id}/read")

    assert response.status_code == 200
    assert response.json()["is_read"] is True


async def test_missing_alert_is_404(client: AsyncClient):
    assert (await client.get("/api/v1/scanner/alerts/9999")).status_code == 404


# ------------------------------------------------------------------ status


async def test_status_never_run(client: AsyncClient):
    body = (await client.get("/api/v1/scanner/status")).json()

    assert body["state"] == "never_run"
    assert body["is_healthy"] is False


async def test_status_distinguishes_quiet_market_from_failure(client: AsyncClient, db_session):
    """The single most important assertion in this file."""
    db_session.add(
        ScanRun(
            started_at=datetime(2026, 7, 28, 13, 25),
            finished_at=datetime(2026, 7, 28, 13, 25, 1),
            status=ScanRunStatus.COMPLETED,
            profile="production",
        )
    )
    await db_session.commit()

    quiet = (await client.get("/api/v1/scanner/status")).json()
    assert quiet["state"] == "ok_no_candidates"
    assert quiet["is_healthy"] is True
    assert "quiet" in quiet["detail"].lower()

    db_session.add(
        ScanRun(
            started_at=datetime(2026, 7, 28, 13, 30),
            finished_at=datetime(2026, 7, 28, 13, 30, 1),
            status=ScanRunStatus.FAILED,
            profile="production",
            error="FeatureRequiresIntraday: needs extended=true bars",
        )
    )
    await db_session.commit()

    broken = (await client.get("/api/v1/scanner/status")).json()
    assert broken["state"] == "failed"
    assert broken["is_healthy"] is False
    assert "outage" in broken["detail"].lower()
    assert broken["last_run"]["error"]

    # A prior success is still reported, so the UI can say when it last worked.
    assert broken["last_successful_run"]["status"] == "completed"


async def test_status_reports_candidates_when_alerts_exist(
    client: AsyncClient, scanner_alert
):
    body = (await client.get("/api/v1/scanner/status")).json()

    assert body["state"] == "ok_with_candidates"
    assert body["alert_count"] == 1


# ------------------------------------------------- session total vs scan result


async def _add_session_alert(db_session, ticker: str, *, is_final_pass: bool, minute: int):
    db_session.add(
        Alert(
            ticker=ticker,
            session_date=SESSION,
            timestamp=datetime(2026, 7, 28, 9, minute),
            scan_timestamp=datetime(2026, 7, 28, 9, minute),
            profile="production",
            gap_pct=5.0,
            confidence_score=0.5,
            is_final_pass=is_final_pass,
        )
    )


async def _add_run(db_session, *, hour: int, minute: int, is_final_pass: bool):
    """A completed run stamped with the ET moment it decided on, as the pipeline does."""
    db_session.add(
        ScanRun(
            started_at=datetime(2026, 7, 28, hour + 4, minute),  # ET -> UTC, summer
            finished_at=datetime(2026, 7, 28, hour + 4, minute, 30),
            status=ScanRunStatus.COMPLETED,
            profile="production",
            stage_counts_json={
                "as_of_et": f"2026-07-28T{hour:02d}:{minute:02d}:00-04:00",
                "is_final_pass": is_final_pass,
                "counts": {"universe": 3964, "risk_filters": 2},
            },
        )
    )


async def test_session_total_is_never_reported_as_the_last_scans_result(
    client: AsyncClient, db_session
):
    """The bug this split exists to prevent: 37 tickers qualified at some point in the
    morning, 11 were still qualifying at 09:25, and the panel headlined 37 as what the
    last scan found — directly above a funnel that ended in 11."""
    await _add_session_alert(db_session, "CNFA", is_final_pass=True, minute=25)
    await _add_session_alert(db_session, "CNFB", is_final_pass=True, minute=25)
    await _add_session_alert(db_session, "FADE", is_final_pass=False, minute=10)
    await _add_run(db_session, hour=9, minute=25, is_final_pass=True)
    await db_session.commit()

    body = (await client.get("/api/v1/scanner/status")).json()

    assert body["alert_count"] == 3
    assert body["confirmed_count"] == 2
    assert body["final_pass_complete"] is True
    # Both numbers present, each labelled — never one standing in for the other.
    assert "2 candidate(s) confirmed at the 09:25 ET pass" in body["detail"]
    assert "3 seen across the session" in body["detail"]


async def test_nothing_is_confirmed_before_the_final_pass(client: AsyncClient, db_session):
    """At 06:40 there is no confirmed set at all. Reporting `confirmed_count` of 0 as a
    result would say "none survived" about a question nobody has asked yet."""
    await _add_session_alert(db_session, "PROV", is_final_pass=False, minute=10)
    await _add_run(db_session, hour=6, minute=40, is_final_pass=False)
    await db_session.commit()

    body = (await client.get("/api/v1/scanner/status")).json()

    assert body["final_pass_complete"] is False
    assert body["confirmed_count"] == 0
    assert body["alert_count"] == 1
    assert "provisional" in body["detail"]
    assert "Nothing is confirmed until the 09:25 ET pass" in body["detail"]


async def test_a_final_pass_that_confirmed_nothing_says_so(client: AsyncClient, db_session):
    """Distinct from the case above, and the reason `final_pass_complete` exists: the
    09:25 pass ran and every candidate had faded by then."""
    await _add_session_alert(db_session, "FADE", is_final_pass=False, minute=10)
    await _add_run(db_session, hour=9, minute=25, is_final_pass=True)
    await db_session.commit()

    body = (await client.get("/api/v1/scanner/status")).json()

    assert body["final_pass_complete"] is True
    assert body["confirmed_count"] == 0
    assert "No candidate survived to the 09:25 ET confirmation pass" in body["detail"]
    assert "1 qualified earlier in the session and faded" in body["detail"]


async def test_a_past_sessions_alerts_are_not_reported_as_awaiting_confirmation(
    client: AsyncClient, db_session
):
    """It is 06:00 the next morning and today has produced nothing yet, so the list on
    screen is yesterday's. Yesterday's 09:25 pass has been and gone; saying otherwise
    would mark a finished session as still pending."""
    await _add_session_alert(db_session, "CNFA", is_final_pass=True, minute=25)
    db_session.add(
        ScanRun(
            started_at=datetime(2026, 7, 29, 10, 0),
            finished_at=datetime(2026, 7, 29, 10, 0, 30),
            status=ScanRunStatus.COMPLETED,
            profile="production",
            stage_counts_json={
                "as_of_et": "2026-07-29T06:00:00-04:00",
                "is_final_pass": False,
                "counts": {"universe": 3964},
            },
        )
    )
    await db_session.commit()

    body = (await client.get("/api/v1/scanner/status")).json()

    assert body["session_date"] == "2026-07-28"
    assert body["final_pass_complete"] is True
    assert body["confirmed_count"] == 1


async def test_a_quiet_session_before_the_final_pass_does_not_claim_to_be_final(
    client: AsyncClient, db_session
):
    """Zero candidates at 06:40 is "none yet", not "none all morning"."""
    await _add_run(db_session, hour=6, minute=40, is_final_pass=False)
    await db_session.commit()

    body = (await client.get("/api/v1/scanner/status")).json()

    assert body["state"] == "ok_no_candidates"
    assert body["is_healthy"] is True
    assert "quiet" in body["detail"].lower()
    assert "yet this session" in body["detail"]


async def test_a_run_stuck_in_running_is_treated_as_failed(client: AsyncClient, db_session):
    """A process that died mid-scan must not look healthy."""
    db_session.add(
        ScanRun(
            started_at=datetime(2026, 7, 28, 13, 25),
            status=ScanRunStatus.RUNNING,
            profile="production",
        )
    )
    await db_session.commit()

    body = (await client.get("/api/v1/scanner/status")).json()
    assert body["state"] == "failed"
    assert body["is_healthy"] is False


async def test_only_skipped_runs_is_healthy_but_distinct_from_never_run(
    client: AsyncClient, db_session
):
    """The cron is demonstrably alive but has never woken inside the window. Healthy —
    and NOT `never_run`, which is a different problem with a different fix."""
    db_session.add(
        ScanRun(
            started_at=datetime(2026, 7, 28, 20, 0),
            finished_at=datetime(2026, 7, 28, 20, 0, 1),
            status=ScanRunStatus.SKIPPED,
            profile="production",
        )
    )
    await db_session.commit()

    body = (await client.get("/api/v1/scanner/status")).json()
    assert body["state"] == "skipped"
    assert body["is_healthy"] is True
    assert body["last_run"] is None
    # The wake-up is still visible — that is where "did the cron fire?" is answered.
    assert [r["status"] for r in body["recent_runs"]] == ["skipped"]


async def test_the_mornings_scan_is_not_buried_by_the_afternoons_skipped_wake_ups(
    client: AsyncClient, db_session
):
    """The cron wakes every 5 minutes until 14:55 UTC, so ~18 `skipped` rows follow the
    09:25 pass every session. If the newest row drove the status, the dashboard would
    read "outside scan window" — with no stage counts — from 09:30 ET until the next
    morning, hiding the very result the panel exists to show."""
    db_session.add(
        ScanRun(
            started_at=datetime(2026, 7, 28, 13, 25),
            finished_at=datetime(2026, 7, 28, 13, 25, 30),
            status=ScanRunStatus.COMPLETED,
            profile="production",
            stage_counts_json={"counts": {"universe": 694}},
        )
    )
    # More skipped wake-ups than /status reads rows, so a Python-side filter over the
    # ten most recent rows would report "no scan has ever run".
    for minute in range(0, 90, 5):
        db_session.add(
            ScanRun(
                started_at=datetime(2026, 7, 28, 13, 30) + timedelta(minutes=minute),
                finished_at=datetime(2026, 7, 28, 13, 30, 1) + timedelta(minutes=minute),
                status=ScanRunStatus.SKIPPED,
                profile="production",
            )
        )
    await db_session.commit()

    body = (await client.get("/api/v1/scanner/status")).json()

    assert body["state"] == "ok_no_candidates"
    assert body["is_healthy"] is True
    assert body["last_run"]["status"] == "completed"
    assert body["last_run"]["stage_counts"]["counts"]["universe"] == 694
    assert body["last_successful_run"]["status"] == "completed"
    # The heartbeats are not hidden, just demoted.
    assert body["recent_runs"][0]["status"] == "skipped"


async def test_a_failure_is_not_masked_by_later_skipped_wake_ups(
    client: AsyncClient, db_session
):
    """The inverse risk of demoting `skipped`: an outage must not scroll off the panel
    because the cron kept waking up harmlessly afterwards."""
    db_session.add(
        ScanRun(
            started_at=datetime(2026, 7, 28, 13, 25),
            finished_at=datetime(2026, 7, 28, 13, 25, 5),
            status=ScanRunStatus.FAILED,
            profile="production",
            error="FeatureRequiresIntraday: needs extended=true bars",
        )
    )
    for minute in range(0, 90, 5):
        db_session.add(
            ScanRun(
                started_at=datetime(2026, 7, 28, 13, 30) + timedelta(minutes=minute),
                status=ScanRunStatus.SKIPPED,
                profile="production",
            )
        )
    await db_session.commit()

    body = (await client.get("/api/v1/scanner/status")).json()

    assert body["state"] == "failed"
    assert body["is_healthy"] is False
    assert "outage" in body["detail"].lower()


async def test_scan_runs_list(client: AsyncClient, scanner_alert):
    body = (await client.get("/api/v1/scanner/scan-runs")).json()

    assert len(body) == 1
    assert body[0]["status"] == "completed"
    assert body[0]["is_demo"] is False
    assert body[0]["stage_counts"]["counts"]["universe"] == 11


async def test_attempted_only_keeps_the_scan_history_readable_under_the_heartbeat_rate(
    client: AsyncClient, db_session
):
    """The tiered cadence turns 65 of a weekday's 84 wake-ups into `skipped` rows, so a
    page of the 20 newest runs is all heartbeats within an hour of the close — the Scans
    page unable to answer the one question it exists for. `attempted_only` is how it does,
    and the default stays unfiltered so "did the cron fire?" is still answerable."""
    db_session.add(
        ScanRun(
            started_at=datetime(2026, 7, 28, 13, 25),
            finished_at=datetime(2026, 7, 28, 13, 25, 30),
            status=ScanRunStatus.COMPLETED,
            profile="production",
            stage_counts_json={"counts": {"universe": 694}},
        )
    )
    # More heartbeats than the page's own limit, both flavours: out-of-window wake-ups
    # after the close, and off-cadence ones from between the morning's passes.
    for minute in range(0, 150, 5):
        db_session.add(
            ScanRun(
                started_at=datetime(2026, 7, 28, 13, 30) + timedelta(minutes=minute),
                finished_at=datetime(2026, 7, 28, 13, 30, 1) + timedelta(minutes=minute),
                status=ScanRunStatus.SKIPPED,
                profile="production",
                stage_counts_json={"skip_reason": "off_cadence" if minute < 60 else "outside_window"},
            )
        )
    await db_session.commit()

    unfiltered = (await client.get("/api/v1/scanner/scan-runs?limit=20")).json()
    attempted = (await client.get("/api/v1/scanner/scan-runs?limit=20&attempted_only=true")).json()

    # Without the filter the morning's scan is nowhere on the page.
    assert {row["status"] for row in unfiltered} == {"skipped"}
    assert [row["status"] for row in attempted] == ["completed"]
    assert attempted[0]["stage_counts"]["counts"]["universe"] == 694


async def test_status_reports_the_last_wake_up_as_well_as_the_last_scan(
    client: AsyncClient, db_session
):
    """With a coarse early cadence an hours-old last scan is normal, so it is no longer
    evidence of a stall. The heartbeat is what says the cron is alive, and the panel needs
    both numbers to tell "asleep on purpose" from "died at 04:15"."""
    db_session.add(
        ScanRun(
            started_at=datetime(2026, 7, 28, 8, 15),
            finished_at=datetime(2026, 7, 28, 8, 16),
            status=ScanRunStatus.COMPLETED,
            profile="production",
            stage_counts_json={"counts": {"universe": 694}},
        )
    )
    db_session.add(
        ScanRun(
            started_at=datetime(2026, 7, 28, 9, 45),
            finished_at=datetime(2026, 7, 28, 9, 45, 1),
            status=ScanRunStatus.SKIPPED,
            profile="production",
            stage_counts_json={"skip_reason": "outside_window"},
        )
    )
    await db_session.commit()

    body = (await client.get("/api/v1/scanner/status")).json()

    assert body["last_run"]["status"] == "completed"
    assert body["last_run"]["started_at"].startswith("2026-07-28T08:15")
    assert body["last_wake_up_at"].startswith("2026-07-28T09:45")
    assert body["is_healthy"] is True
