"""Tests for the scanner API.

The `/status` endpoint gets the most attention: it is the endpoint that carries the
quiet-market-vs-outage distinction into the UI, and a client that cannot tell them apart
will eventually trust neither.
"""

from datetime import date, datetime

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
        symbol="LOWF",
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
    # The DB column is `symbol`; the contract says `ticker`.
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
            symbol="ADBE",
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
            symbol="BRKO",
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


async def test_skipped_run_is_healthy_but_distinct(client: AsyncClient, db_session):
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


async def test_scan_runs_list(client: AsyncClient, scanner_alert):
    body = (await client.get("/api/v1/scanner/scan-runs")).json()

    assert len(body) == 1
    assert body[0]["status"] == "completed"
    assert body[0]["is_demo"] is False
    assert body[0]["stage_counts"]["counts"]["universe"] == 11
