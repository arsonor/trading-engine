"""Market Data API endpoints."""

from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, HTTPException, Query

from app.schemas import Bar, MarketData, Timeframe

router = APIRouter()


# Placeholder data for demo purposes
# In production, this will use the Alpaca client
DEMO_SYMBOLS = {
    "AAPL": {"price": 185.50, "prev_close": 183.00},
    "TSLA": {"price": 250.00, "prev_close": 248.50},
    "NVDA": {"price": 480.00, "prev_close": 475.00},
    "MSFT": {"price": 375.00, "prev_close": 372.00},
    "GOOGL": {"price": 140.00, "prev_close": 138.50},
}


@router.get("/{symbol}", response_model=MarketData)
async def get_market_data(symbol: str) -> MarketData:
    """Get current market data for a symbol."""
    symbol = symbol.upper()

    # Check if symbol exists (demo)
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

    # Check if symbol exists (demo)
    if symbol not in DEMO_SYMBOLS:
        raise HTTPException(status_code=404, detail=f"Symbol '{symbol}' not found")

    # Generate demo bars
    demo = DEMO_SYMBOLS[symbol]
    base_price = demo["price"]

    # Default time range
    if end is None:
        end = datetime.utcnow()
    if start is None:
        start = end - timedelta(hours=6)

    # Generate bars based on timeframe
    bars = []
    current_time = start
    price = base_price - 2.0  # Start slightly lower

    while current_time < end and len(bars) < limit:
        # Simple price simulation
        import random

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
