"""Watchlist API endpoints."""

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models import Watchlist as WatchlistModel
from app.schemas import WatchlistCreate, WatchlistItem
from app.services.stream_manager import get_stream_manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("", response_model=List[WatchlistItem])
async def get_watchlist(
    db: AsyncSession = Depends(get_db),
) -> List[WatchlistItem]:
    """Get all watchlist items."""
    query = select(WatchlistModel).order_by(WatchlistModel.added_at.desc())
    result = await db.execute(query)
    items = result.scalars().all()

    return [
        WatchlistItem(
            id=item.id,
            symbol=item.symbol,
            added_at=item.added_at,
            is_active=item.is_active,
            notes=item.notes,
        )
        for item in items
    ]


@router.post("", response_model=WatchlistItem, status_code=201)
async def add_to_watchlist(
    item_create: WatchlistCreate,
    db: AsyncSession = Depends(get_db),
) -> WatchlistItem:
    """Add a symbol to the watchlist."""
    symbol = item_create.symbol.upper()

    # Check for duplicate
    existing_query = select(WatchlistModel).where(WatchlistModel.symbol == symbol)
    existing = (await db.execute(existing_query)).scalar_one_or_none()
    if existing:
        raise HTTPException(
            status_code=409, detail=f"Symbol '{symbol}' is already in watchlist"
        )

    # Create item
    item = WatchlistModel(
        symbol=symbol,
        notes=item_create.notes,
    )

    db.add(item)
    await db.commit()
    await db.refresh(item)

    # Auto-subscribe to the new symbol for real-time data
    try:
        stream_manager = get_stream_manager()
        if stream_manager.is_running:
            await stream_manager.subscribe([symbol])
            logger.info(f"Auto-subscribed to new watchlist symbol: {symbol}")
    except Exception as e:
        logger.warning(f"Failed to auto-subscribe to {symbol}: {e}")

    return WatchlistItem(
        id=item.id,
        symbol=item.symbol,
        added_at=item.added_at,
        is_active=item.is_active,
        notes=item.notes,
    )


@router.delete("/{symbol}", status_code=204)
async def remove_from_watchlist(
    symbol: str,
    db: AsyncSession = Depends(get_db),
) -> None:
    """Remove a symbol from the watchlist."""
    symbol = symbol.upper()

    query = select(WatchlistModel).where(WatchlistModel.symbol == symbol)
    result = await db.execute(query)
    item = result.scalar_one_or_none()

    if not item:
        raise HTTPException(
            status_code=404, detail=f"Symbol '{symbol}' not found in watchlist"
        )

    await db.delete(item)
    await db.commit()

    # Auto-unsubscribe from the removed symbol
    try:
        stream_manager = get_stream_manager()
        if stream_manager.is_running:
            await stream_manager.unsubscribe([symbol])
            logger.info(f"Auto-unsubscribed from removed watchlist symbol: {symbol}")
    except Exception as e:
        logger.warning(f"Failed to auto-unsubscribe from {symbol}: {e}")
