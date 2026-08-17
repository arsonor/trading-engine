"""Scanner API — session alerts, scan status and tunable thresholds.

Mounted under `/api/v1/scanner`. The prefix originally kept these routes clear of the
v1 rule-engine `/alerts` routes; those are gone as of Phase 3.5, but the prefix stays
because the frontend and the published contract both use it.

The `/status` endpoint carries the distinction this whole phase turns on: a scan that
found nothing and a scan that broke are different `state` values with different copy, so
the dashboard cannot accidentally render them the same way.

It carries a second one now: **a session total is not a scan result.** Alerts dedup per
`(ticker, session_date)` across the morning's ~66 passes, so the alert count is "distinct
tickers that qualified at any point since 04:00", while the funnel on the same panel
reports the last pass alone. Reporting the first under a per-scan label made the panel
contradict itself — 37 in the headline over a funnel ending in 11. Both numbers are
useful; they are now returned as separate, separately labelled fields.
"""

import logging
from datetime import date, datetime

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


def _run_session_date(stage_counts: dict | None) -> date | None:
    """The ET session a `scan_runs` row belongs to, or None if it cannot be told.

    `started_at` is UTC, so a 04:00-09:25 ET session straddles no UTC date in summer but
    the derivation is still not free — the pipeline already stamps the ET moment it
    decided on into `stage_counts_json`, so that is what is read here.
    """
    if not stage_counts:
        return None
    raw = stage_counts.get("as_of_et")
    if not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw).date()
    except ValueError:  # pragma: no cover - only a hand-edited row gets here
        return None


def _final_pass_complete(last_run: ScanRun | None, session_date: date | None) -> bool:
    """Whether the authoritative 09:25 ET pass has already run for the session on screen.

    This is the difference between "0 of 37 survived to 09:25" and "nothing is confirmed
    yet, it is 06:40" — two very different things to tell someone deciding what to trade,
    and indistinguishable from a confirmed count of zero. The pipeline stamps
    `is_final_pass` onto every run's `stage_counts_json`, so the answer is durable rather
    than recomputed from the clock at request time.
    """
    if last_run is None:
        return False

    stage_counts = last_run.stage_counts_json
    run_date = _run_session_date(stage_counts)
    if run_date is not None and session_date is not None and run_date != session_date:
        # The alerts on screen belong to an earlier session, which is over: its 09:25
        # pass has been and gone. Reading this morning's 06:00 run as "yesterday's
        # candidates are not confirmed yet" would be false.
        return True

    return bool((stage_counts or {}).get("is_final_pass"))


def _candidate_detail(alert_count: int, confirmed_count: int, final_pass_done: bool) -> str:
    """State both numbers, each labelled for what it is.

    Never collapse them into one. The session total is genuinely useful — it is simply
    not the last scan's result, and a headline that says otherwise is contradicted by the
    funnel rendered directly beneath it.
    """
    if not final_pass_done:
        return (
            f"{alert_count} provisional candidate(s) so far this session. "
            f"Nothing is confirmed until the 09:25 ET pass."
        )
    if confirmed_count:
        return (
            f"{confirmed_count} candidate(s) confirmed at the 09:25 ET pass · "
            f"{alert_count} seen across the session."
        )
    return (
        f"No candidate survived to the 09:25 ET confirmation pass. "
        f"{alert_count} qualified earlier in the session and faded."
    )


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
    limit: int = Query(20, ge=1, le=100),
    attempted_only: bool = Query(
        False,
        description=(
            "Exclude `skipped` heartbeat wake-ups. The tiered cadence skips 65 of a "
            "weekday's 84 wake-ups, so an unfiltered page of 20 shows nothing else."
        ),
    ),
    db: AsyncSession = Depends(get_db),
) -> list[ScanRunOut]:
    """Recent scan runs, newest first.

    `attempted_only` exists because of the cadence, not as a convenience. Heartbeats
    outnumbered real passes ~18 to 66 before Follow-up A and outnumber them ~65 to 19
    after it, so the newest 20 rows became all heartbeats within an hour of the close —
    the Scans page's own answer to "is the scanner working?" buried under the evidence
    that the cron is alive. Default `False` keeps the existing contract: the heartbeats are
    still queryable, and that is still where "did the cron fire?" is answered.
    """
    stmt = select(ScanRun)
    if attempted_only:
        stmt = stmt.where(ScanRun.status != ScanRunStatus.SKIPPED)
    stmt = stmt.order_by(ScanRun.started_at.desc()).limit(limit)
    rows = (await db.execute(stmt)).scalars().all()
    return [ScanRunOut.from_model(row) for row in rows]


@router.get("/status", response_model=ScannerStatus)
async def get_scanner_status(db: AsyncSession = Depends(get_db)) -> ScannerStatus:
    """Scanner health, with quiet-market and outage kept strictly distinct."""
    recent = (
        (await db.execute(select(ScanRun).order_by(ScanRun.started_at.desc()).limit(10)))
        .scalars()
        .all()
    )

    # `skipped` rows are the cron's heartbeat, not scans: 65 of a weekday's 84 wake-ups
    # since the cadence was tiered, and they no longer only follow the session — an
    # off-cadence heartbeat lands between passes all morning. Taking `recent[0]` as "the
    # last scan" would make the dashboard read "outside scan window", with no stage counts,
    # for most of the day. So the state is computed from the last run that ATTEMPTED work,
    # and each of these is its own query rather than a scan of `recent`: ten heartbeats is
    # a couple of hours, so filtering the list in Python would report `None` by 05:00.
    #
    # `last_wake_up` is still returned, as `last_wake_up_at`: with a coarse cadence an
    # hours-old `last_run` is normal, and the heartbeat is what says the cron is alive.
    last_wake_up = recent[0] if recent else None
    last_run = await db.scalar(
        select(ScanRun)
        .where(ScanRun.status != ScanRunStatus.SKIPPED)
        .order_by(ScanRun.started_at.desc())
        .limit(1)
    )
    last_success = await db.scalar(
        select(ScanRun)
        .where(ScanRun.status == ScanRunStatus.COMPLETED)
        .order_by(ScanRun.started_at.desc())
        .limit(1)
    )

    session_date = await db.scalar(
        select(func.max(Alert.session_date)).where(Alert.session_date.isnot(None))
    )
    # Two counts, because they answer two different questions. `alert_count` is every
    # ticker that qualified at any point since 04:00 — one row per (ticker, session),
    # updated in place. `confirmed_count` is how many of them still qualified at the
    # authoritative 09:25 pass, which is the number a user at 09:26 is actually asking
    # for. The rest faded: their gap closed, RVOL fell away, or they hit resistance.
    alert_count = 0
    confirmed_count = 0
    if session_date is not None:
        alert_count = (
            await db.scalar(
                select(func.count(Alert.id)).where(Alert.session_date == session_date)
            )
            or 0
        )
        confirmed_count = (
            await db.scalar(
                select(func.count(Alert.id)).where(
                    Alert.session_date == session_date, Alert.is_final_pass.is_(True)
                )
            )
            or 0
        )

    final_pass_done = _final_pass_complete(last_run, session_date)

    if last_wake_up is None:
        state, detail, healthy = (
            STATE_NEVER_RUN,
            "The scanner has never run. No data has been collected yet.",
            False,
        )
    elif last_run is None:
        # The cron is demonstrably alive but has not yet had a chance to scan — a fresh
        # deployment, or a restore whose only rows are heartbeats. Healthy, and NOT
        # "never run": those are different problems with different fixes.
        state, detail, healthy = (
            STATE_SKIPPED,
            "The scanner has woken up but every wake-up so far fell outside the "
            "04:00-09:25 ET window, so no scan has run yet.",
            True,
        )
    elif last_run.status == ScanRunStatus.FAILED:
        state, detail, healthy = (
            STATE_FAILED,
            f"The last scan FAILED: {last_run.error or 'no error recorded'}. "
            f"This is an outage — not a quiet market.",
            False,
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
            _candidate_detail(alert_count, confirmed_count, final_pass_done),
            True,
        )
    elif final_pass_done:
        state, detail, healthy = (
            STATE_OK_NO_CANDIDATES,
            "Last scan completed successfully and found no candidates. "
            "The scanner is working; the market is quiet.",
            True,
        )
    else:
        state, detail, healthy = (
            STATE_OK_NO_CANDIDATES,
            "Last scan completed successfully and no candidate has qualified yet this "
            "session. The scanner is working; the market is quiet so far.",
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
        confirmed_count=confirmed_count,
        final_pass_complete=final_pass_done,
        last_wake_up_at=last_wake_up.started_at if last_wake_up else None,
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
