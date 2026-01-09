"""Market Data API endpoints."""

import random
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app.config import get_settings
from app.schemas import Bar, MarketData, Timeframe
from app.services.alert_generator import get_alert_generator
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


# ============== Test/Simulation Endpoints ==============


class SimulateMarketDataRequest(BaseModel):
    """Request body for simulating market data."""

    symbol: str = Field(..., description="Stock symbol (e.g., AAPL)")
    price: float = Field(..., gt=0, description="Current price")
    volume: Optional[int] = Field(1000000, ge=0, description="Trading volume")
    prev_close: Optional[float] = Field(None, gt=0, description="Previous close price")
    day_high: Optional[float] = Field(None, gt=0, description="Day's high")
    day_low: Optional[float] = Field(None, gt=0, description="Day's low")
    day_open: Optional[float] = Field(None, gt=0, description="Day's open")


class SimulateMarketDataResponse(BaseModel):
    """Response from market data simulation."""

    symbol: str
    price: float
    rules_evaluated: int
    alerts_triggered: int
    alerts: List[Dict[str, Any]]
    message: str
    debug: Optional[Dict[str, Any]] = None


@router.post("/simulate", response_model=SimulateMarketDataResponse)
async def simulate_market_data(request: SimulateMarketDataRequest) -> SimulateMarketDataResponse:
    """
    Simulate market data to test rule evaluation and alert generation.

    This endpoint allows testing the AlertGenerator without live market data.
    It creates a MarketData object from the request and passes it through
    the alert generation pipeline.

    **Example request:**
    ```json
    {
        "symbol": "AAPL",
        "price": 150.0,
        "volume": 1000000
    }
    ```

    If you have a rule like "price > 100", this will trigger an alert.
    """
    symbol = request.symbol.upper()

    # Build MarketData from request
    market_data = MarketData(
        symbol=symbol,
        price=request.price,
        volume=request.volume,
        timestamp=datetime.utcnow(),
        prev_close=request.prev_close,
        day_high=request.day_high or request.price,
        day_low=request.day_low or request.price,
        day_open=request.day_open or request.price,
    )

    # Get alert generator and ensure it's running
    alert_generator = get_alert_generator()
    if not alert_generator._running:
        await alert_generator.start()

    # Force refresh rules cache to pick up any new rules
    await alert_generator.refresh_rules_cache(force=True)

    # Capture initial state to count new alerts
    rules_count = len(alert_generator._rules_cache)

    # Process the simulated market data
    alerts_created = await alert_generator._evaluate_and_generate(
        symbol,
        alert_generator._enrich_market_data(symbol, market_data),
    )

    # Format alerts for response
    alerts_data = []
    for alert in alerts_created:
        alerts_data.append({
            "id": alert.id,
            "symbol": alert.symbol,
            "setup_type": alert.setup_type,
            "entry_price": alert.entry_price,
            "stop_loss": alert.stop_loss,
            "target_price": alert.target_price,
            "confidence_score": alert.confidence_score,
            "rule_id": alert.rule_id,
        })

    # Build debug info
    debug_info = {
        "rules_in_cache": [
            {"id": rid, "name": rule_def.name, "enabled": rule_def.enabled}
            for rid, (_, rule_def) in alert_generator._rules_cache.items()
        ],
        "market_data_used": alert_generator._enrich_market_data(symbol, market_data),
    }

    return SimulateMarketDataResponse(
        symbol=symbol,
        price=request.price,
        rules_evaluated=rules_count,
        alerts_triggered=len(alerts_created),
        alerts=alerts_data,
        message=f"Simulated {symbol} @ ${request.price:.2f} - {len(alerts_created)} alert(s) triggered",
        debug=debug_info,
    )
