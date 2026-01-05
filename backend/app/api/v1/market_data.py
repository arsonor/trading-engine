"""Market Data API endpoints."""

import random
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.config import get_settings
from app.schemas import Bar, MarketData, Timeframe
from app.services.alpaca_client import get_alpaca_client

router = APIRouter()

settings = get_settings()

# Placeholder data for demo purposes when Alpaca is not configured
DEMO_SYMBOLS = {
    "AAPL": {"price": 185.50, "prev_close": 183.00},
    "TSLA": {"price": 250.00, "prev_close": 248.50},
    "NVDA": {"price": 480.00, "prev_close": 475.00},
    "MSFT": {"price": 375.00, "prev_close": 372.00},
    "GOOGL": {"price": 140.00, "prev_close": 138.50},
}


def _generate_demo_market_data(symbol: str) -> MarketData:
    """Generate demo market data for a symbol."""
    if symbol not in DEMO_SYMBOLS:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")

    demo = DEMO_SYMBOLS[symbol]
    price = demo["price"]
    prev_close = demo["prev_close"]
    change = price - prev_close
    change_percent = (change / prev_close) * 100

    return MarketData(
        symbol=symbol,
        price=price,
        bid=price - 0.02,
        ask=price + 0.02,
        bid_size=100,
        ask_size=200,
        volume=45678900,
        timestamp=datetime.utcnow(),
        change=round(change, 2),
        change_percent=round(change_percent, 2),
        day_high=price + 1.50,
        day_low=price - 2.00,
        day_open=prev_close + 0.50,
        prev_close=prev_close,
        pre_market_price=price - 0.25,
        after_hours_price=None,
        vwap=price - 0.15,
    )


def _generate_demo_bars(
    symbol: str, timeframe: Timeframe, start: datetime, end: datetime, limit: int
) -> List[Bar]:
    """Generate demo bar data for a symbol."""
    if symbol not in DEMO_SYMBOLS:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")

    demo = DEMO_SYMBOLS[symbol]
    base_price = demo["price"]

    bars = []
    current_time = start
    price = base_price - 2.0

    while current_time < end and len(bars) < limit:
        change = random.uniform(-0.5, 0.5)
        open_price = price
        close_price = price + change
        high = max(open_price, close_price) + random.uniform(0, 0.3)
        low = min(open_price, close_price) - random.uniform(0, 0.3)
        volume = random.randint(10000, 100000)

        bars.append(
            Bar(
                timestamp=current_time,
                open=round(open_price, 2),
                high=round(high, 2),
                low=round(low, 2),
                close=round(close_price, 2),
                volume=volume,
                vwap=round((high + low + close_price) / 3, 2),
                trade_count=random.randint(100, 1000),
            )
        )

        price = close_price

        # Increment based on timeframe
        if timeframe == Timeframe.MIN_1:
            current_time += timedelta(minutes=1)
        elif timeframe == Timeframe.MIN_5:
            current_time += timedelta(minutes=5)
        elif timeframe == Timeframe.MIN_15:
            current_time += timedelta(minutes=15)
        elif timeframe == Timeframe.HOUR_1:
            current_time += timedelta(hours=1)
        elif timeframe == Timeframe.DAY_1:
            current_time += timedelta(days=1)

    return bars


@router.get("/{symbol}", response_model=MarketData)
async def get_market_data(symbol: str) -> MarketData:
    """Get current market data for a symbol."""
    symbol = symbol.upper()

    # Use Alpaca if configured, otherwise use demo data
    if settings.alpaca_api_key and settings.alpaca_secret_key:
        client = get_alpaca_client()
        market_data = await client.get_snapshot(symbol)

        if market_data is None:
            # Fall back to latest quote
            market_data = await client.get_latest_quote(symbol)

        if market_data is None:
            raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")

        return market_data

    # Demo mode
    return _generate_demo_market_data(symbol)


@router.get("/{symbol}/history", response_model=List[Bar])
async def get_historical_bars(
    symbol: str,
    timeframe: Timeframe = Query(Timeframe.MIN_1, description="Bar timeframe"),
    start: Optional[datetime] = Query(None, description="Start datetime"),
    end: Optional[datetime] = Query(None, description="End datetime"),
    limit: int = Query(100, ge=1, le=10000, description="Maximum bars to return"),
) -> List[Bar]:
    """Get historical OHLCV bars for a symbol."""
    symbol = symbol.upper()

    # Default time range
    if end is None:
        end = datetime.utcnow()
    if start is None:
        start = end - timedelta(hours=6)

    # Use Alpaca if configured, otherwise use demo data
    if settings.alpaca_api_key and settings.alpaca_secret_key:
        client = get_alpaca_client()
        bars = await client.get_bars(
            symbol=symbol,
            timeframe=timeframe,
            start=start,
            end=end,
            limit=limit,
        )

        if not bars:
            raise HTTPException(status_code=404, detail=f"No data found for symbol '{symbol}'")

        return bars

    # Demo mode
    return _generate_demo_bars(symbol, timeframe, start, end, limit)
