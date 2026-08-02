"""Scanner API — session alerts, scan status and tunable thresholds.

Mounted under `/api/v1/scanner`. The prefix originally kept these routes clear of the
v1 rule-engine `/alerts` routes; those are gone as of Phase 3.5, but the prefix stays
because the frontend and the published contract both use it.

The `/status` endpoint carries the distinction this whole phase turns on: a scan that
found nothing and a scan that broke are different `state` values with different copy, so
the dashboard cannot accidentally render them the same way.
"""

import logging
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.alert import Alert
from app.models.scan_run import ScanRun, ScanRunStatus
from app.schemas.scanner import (
    ScannerAlert,
    ScannerAlertListResponse,
    ScannerStatus,
    ScanRunOut,
    ThresholdSettings,
    ThresholdSettingsUpdate,
)
from app.services.scanner.settings_store import (
    OVERRIDABLE_FIELDS,
    InvalidThresholdOverrideError,
    ScannerSettingsStore,
)

logger = logging.getLogger(__name__)
router = APIRouter()

STATE_NEVER_RUN = "never_run"
STATE_OK_WITH_CANDIDATES = "ok_with_candidates"
STATE_OK_NO_CANDIDATES = "ok_no_candidates"
STATE_FAILED = "failed"
STATE_SKIPPED = "skipped"


@router.get("/alerts", response_model=ScannerAlertListResponse)
async def list_scanner_alerts(
    session_date: date | None = Query(None, description="Defaults to the latest session"),
    profile: str | None = Query(None, description="Filter by threshold profile"),
    unread_only: bool = Query(False),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> ScannerAlertListResponse:
    """Alerts for a trading session, strongest confidence first."""
    target_date = session_date
    if target_date is None:
        target_date = await db.scalar(
            select(func.max(Alert.session_date)).where(Alert.session_date.isnot(None))
        )

    if target_date is None:
        return ScannerAlertListResponse(items=[], total=0, session_date=None)

    stmt = select(Alert).where(Alert.session_date == target_date)
    if profile:
        stmt = stmt.where(Alert.profile == profile)
    if unread_only:
        stmt = stmt.where(Alert.is_read.is_(False))

    stmt = stmt.order_by(Alert.confidence_score.desc().nullslast(), Alert.ticker).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    items = [ScannerAlert.from_model(row) for row in rows]

    return ScannerAlertListResponse(
        items=items,
        total=len(items),
        session_date=target_date,
        has_demo_alerts=any(item.is_demo for item in items),
    )


@router.get("/alerts/{alert_id}", response_model=ScannerAlert)
async def get_scanner_alert(alert_id: int, db: AsyncSession = Depends(get_db)) -> ScannerAlert:
    """One alert, including the full confidence-score breakdown."""
    alert = await db.scalar(select(Alert).where(Alert.id == alert_id))
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    return ScannerAlert.from_model(alert)


@router.post("/alerts/{alert_id}/read", response_model=ScannerAlert)
async def mark_alert_read(alert_id: int, db: AsyncSession = Depends(get_db)) -> ScannerAlert:
    """Mark an alert as read."""
    alert = await db.scalar(select(Alert).where(Alert.id == alert_id))
    if alert is None:
        raise HTTPException(status_code=404, detail=f"Alert {alert_id} not found")
    alert.is_read = True
    await db.commit()
    await db.refresh(alert)
    return ScannerAlert.from_model(alert)


@router.get("/scan-runs", response_model=list[ScanRunOut])
async def list_scan_runs(
    limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db)
) -> list[ScanRunOut]:
    """Recent scan runs, newest first."""
    rows = (
        (await db.execute(select(ScanRun).order_by(ScanRun.started_at.desc()).limit(limit)))
        .scalars()
        .all()
    )
    return [ScanRunOut.from_model(row) for row in rows]


@router.get("/status", response_model=ScannerStatus)
async def get_scanner_status(db: AsyncSession = Depends(get_db)) -> ScannerStatus:
    """Scanner health, with quiet-market and outage kept strictly distinct."""
    recent = (
        (await db.execute(select(ScanRun).order_by(ScanRun.started_at.desc()).limit(10)))
        .scalars()
        .all()
    )
    last_run = recent[0] if recent else None
    last_success = next((r for r in recent if r.status == ScanRunStatus.COMPLETED), None)

    session_date = await db.scalar(
        select(func.max(Alert.session_date)).where(Alert.session_date.isnot(None))
    )
    alert_count = 0
    if session_date is not None:
        alert_count = (
            await db.scalar(
                select(func.count(Alert.id)).where(Alert.session_date == session_date)
            )
            or 0
        )

    if last_run is None:
        state, detail, healthy = (
            STATE_NEVER_RUN,
            "The scanner has never run. No data has been collected yet.",
            False,
        )
    elif last_run.status == ScanRunStatus.FAILED:
        state, detail, healthy = (
            STATE_FAILED,
            f"The last scan FAILED: {last_run.error or 'no error recorded'}. "
            f"This is an outage — not a quiet market.",
            False,
        )
    elif last_run.status == ScanRunStatus.SKIPPED:
        state, detail, healthy = (
            STATE_SKIPPED,
            "The last wake-up fell outside the 04:00-09:25 ET scan window, so no scan ran.",
            True,
        )
    elif last_run.status == ScanRunStatus.RUNNING:
        state, detail, healthy = (
            STATE_FAILED,
            "A scan started but never finished — the process likely died mid-run.",
            False,
        )
    elif alert_count:
        state, detail, healthy = (
            STATE_OK_WITH_CANDIDATES,
            f"Last scan completed and surfaced {alert_count} candidate(s).",
            True,
        )
    else:
        state, detail, healthy = (
            STATE_OK_NO_CANDIDATES,
            "Last scan completed successfully and found no candidates. "
            "The scanner is working; the market is quiet.",
            True,
        )

    return ScannerStatus(
        last_run=ScanRunOut.from_model(last_run) if last_run else None,
        last_successful_run=ScanRunOut.from_model(last_success) if last_success else None,
        is_healthy=healthy,
        state=state,
        detail=detail,
        session_date=session_date,
        alert_count=alert_count,
        recent_runs=[ScanRunOut.from_model(r) for r in recent],
    )


@router.get("/settings", response_model=ThresholdSettings)
async def get_scanner_settings() -> ThresholdSettings:
    """Effective thresholds: environment defaults with any stored overrides applied."""
    store = ScannerSettingsStore()
    profile = await store.resolve_profile()
    _, overrides = await store.get_overrides()

    return ThresholdSettings(
        profile=profile.name,
        is_demo=profile.is_demo,
        float_max=profile.float_max,
        avg_volume_min=profile.avg_volume_min,
        gap_min=profile.gap_min,
        gap_max=profile.gap_max,
        rvol_min=profile.rvol_min,
        upside_min=profile.upside_min,
        price_floor=profile.price_floor,
        dollar_volume_min=profile.dollar_volume_min,
        overrides=overrides,
        # Derived from the effective fields, never a stored string — see
        # ThresholdProfile.describe().
        description=profile.describe(),
    )


@router.put("/settings", response_model=ThresholdSettings)
async def update_scanner_settings(update: ThresholdSettingsUpdate) -> ThresholdSettings:
    """Persist threshold/profile edits. They take effect on the next scan, no redeploy."""
    store = ScannerSettingsStore()
    stored_profile, existing = await store.get_overrides()

    merged = {**existing, **update.threshold_overrides()}
    profile_name = update.profile if update.profile is not None else stored_profile

    try:
        await store.save(profile=profile_name, overrides=merged)
    except InvalidThresholdOverrideError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return await get_scanner_settings()


@router.delete("/settings", response_model=ThresholdSettings)
async def reset_scanner_settings() -> ThresholdSettings:
    """Drop all overrides and fall back to the environment defaults."""
    await ScannerSettingsStore().clear()
    return await get_scanner_settings()


@router.get("/settings/fields", response_model=list[str])
async def list_overridable_fields() -> list[str]:
    """Which thresholds the Settings screen may edit."""
    return list(OVERRIDABLE_FIELDS)
