"""Alerts API endpoints."""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.models import Alert as AlertModel
from app.schemas import (
    Alert,
    AlertListResponse,
    AlertStats,
    AlertUpdate,
    SetupType,
)

router = APIRouter()


@router.get("", response_model=AlertListResponse)
async def list_alerts(
    symbol: Optional[str] = Query(None, description="Filter by ticker symbol"),
    setup_type: Optional[SetupType] = Query(None, description="Filter by setup type"),
    start_date: Optional[datetime] = Query(None, description="Filter alerts after this date"),
    end_date: Optional[datetime] = Query(None, description="Filter alerts before this date"),
    is_read: Optional[bool] = Query(None, description="Filter by read status"),
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=100, description="Items per page"),
    db: AsyncSession = Depends(get_db),
) -> AlertListResponse:
    """List alerts with pagination and filtering."""
    # Build query with eager loading of rule relationship
    query = select(AlertModel).options(selectinload(AlertModel.rule))

    if symbol:
        query = query.where(AlertModel.symbol == symbol.upper())
    if setup_type:
        query = query.where(AlertModel.setup_type == setup_type.value)
    if start_date:
        query = query.where(AlertModel.timestamp >= start_date)
    if end_date:
        query = query.where(AlertModel.timestamp <= end_date)
    if is_read is not None:
        query = query.where(AlertModel.is_read == is_read)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_query)).scalar() or 0

    # Apply pagination
    offset = (page - 1) * page_size
    query = query.order_by(AlertModel.timestamp.desc()).offset(offset).limit(page_size)

    # Execute query
    result = await db.execute(query)
    alerts = result.scalars().all()

    # Convert to response models
    items = []
    for alert in alerts:
        alert_dict = {
            "id": alert.id,
            "rule_id": alert.rule_id,
            "rule_name": alert.rule.name if alert.rule else None,
            "symbol": alert.symbol,
            "timestamp": alert.timestamp,
            "setup_type": alert.setup_type,
            "entry_price": alert.entry_price,
            "stop_loss": alert.stop_loss,
            "target_price": alert.target_price,
            "confidence_score": alert.confidence_score,
            "market_data": alert.market_data_json,
            "is_read": alert.is_read,
            "created_at": alert.created_at,
        }
        items.append(Alert(**alert_dict))

    return AlertListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        has_next=offset + len(items) < total,
        has_prev=page > 1,
    )


@router.get("/stats", response_model=AlertStats)
async def get_alert_stats(
    db: AsyncSession = Depends(get_db),
) -> AlertStats:
    """Get alert statistics."""
    # Total alerts
    total_query = select(func.count(AlertModel.id))
    total_alerts = (await db.execute(total_query)).scalar() or 0

    # Alerts today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    today_query = select(func.count(AlertModel.id)).where(AlertModel.timestamp >= today_start)
    alerts_today = (await db.execute(today_query)).scalar() or 0

    # Unread count
    unread_query = select(func.count(AlertModel.id)).where(AlertModel.is_read == False)  # noqa
    unread_count = (await db.execute(unread_query)).scalar() or 0

    # By setup type
    by_type_query = select(AlertModel.setup_type, func.count(AlertModel.id)).group_by(
        AlertModel.setup_type
    )
    by_type_result = await db.execute(by_type_query)
    by_setup_type = {row[0]: row[1] for row in by_type_result.all()}

    # By symbol (top 10)
    by_symbol_query = (
        select(AlertModel.symbol, func.count(AlertModel.id))
        .group_by(AlertModel.symbol)
        .order_by(func.count(AlertModel.id).desc())
        .limit(10)
    )
    by_symbol_result = await db.execute(by_symbol_query)
    by_symbol = {row[0]: row[1] for row in by_symbol_result.all()}

    # Average confidence
    avg_conf_query = select(func.avg(AlertModel.confidence_score)).where(
        AlertModel.confidence_score.isnot(None)
    )
    avg_confidence = (await db.execute(avg_conf_query)).scalar()

    return AlertStats(
        total_alerts=total_alerts,
        alerts_today=alerts_today,
        unread_count=unread_count,
        by_setup_type=by_setup_type,
        by_symbol=by_symbol,
        avg_confidence=round(avg_confidence, 2) if avg_confidence else None,
    )


@router.get("/{alert_id}", response_model=Alert)
async def get_alert(
    alert_id: int,
    db: AsyncSession = Depends(get_db),
) -> Alert:
    """Get alert by ID."""
    query = select(AlertModel).options(selectinload(AlertModel.rule)).where(AlertModel.id == alert_id)
    result = await db.execute(query)
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert with ID {alert_id} not found")

    return Alert(
        id=alert.id,
        rule_id=alert.rule_id,
        rule_name=alert.rule.name if alert.rule else None,
        symbol=alert.symbol,
        timestamp=alert.timestamp,
        setup_type=alert.setup_type,
        entry_price=alert.entry_price,
        stop_loss=alert.stop_loss,
        target_price=alert.target_price,
        confidence_score=alert.confidence_score,
        market_data=alert.market_data_json,
        is_read=alert.is_read,
        created_at=alert.created_at,
    )


@router.patch("/{alert_id}", response_model=Alert)
async def update_alert(
    alert_id: int,
    alert_update: AlertUpdate,
    db: AsyncSession = Depends(get_db),
) -> Alert:
    """Update alert (e.g., mark as read)."""
    query = select(AlertModel).options(selectinload(AlertModel.rule)).where(AlertModel.id == alert_id)
    result = await db.execute(query)
    alert = result.scalar_one_or_none()

    if not alert:
        raise HTTPException(status_code=404, detail=f"Alert with ID {alert_id} not found")

    # Update fields
    if alert_update.is_read is not None:
        alert.is_read = alert_update.is_read

    await db.commit()
    await db.refresh(alert)

    return Alert(
        id=alert.id,
        rule_id=alert.rule_id,
        rule_name=alert.rule.name if alert.rule else None,
        symbol=alert.symbol,
        timestamp=alert.timestamp,
        setup_type=alert.setup_type,
        entry_price=alert.entry_price,
        stop_loss=alert.stop_loss,
        target_price=alert.target_price,
        confidence_score=alert.confidence_score,
        market_data=alert.market_data_json,
        is_read=alert.is_read,
        created_at=alert.created_at,
    )
