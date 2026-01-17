"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.v1.router import api_router
from app.api.v1.websocket import get_manager
from app.config import get_settings
from app.core.database import async_session_maker, close_db, init_db
from app.models import Watchlist as WatchlistModel
from app.schemas import HealthResponse, HealthStatus
from app.services.alert_generator import get_alert_generator
from app.services.stream_manager import get_stream_manager

logger = logging.getLogger(__name__)
settings = get_settings()


async def broadcast_trade(symbol: str, market_data) -> None:
    """Broadcast trade data to WebSocket subscribers."""
    manager = get_manager()
    await manager.broadcast_to_symbol(
        symbol,
        {
            "type": "market_data",
            "data": market_data.model_dump(mode="json"),
        },
    )


async def broadcast_quote(symbol: str, market_data) -> None:
    """Broadcast quote data to WebSocket subscribers."""
    manager = get_manager()
    await manager.broadcast_to_symbol(
        symbol,
        {
            "type": "market_data",
            "data": market_data.model_dump(mode="json"),
        },
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    await init_db()

    # Initialize alert generator
    alert_generator = get_alert_generator()

    # Create combined callbacks that broadcast market data AND generate alerts
    async def on_trade_with_alerts(symbol: str, market_data) -> None:
        """Handle trade data: broadcast to WebSocket AND generate alerts."""
        await broadcast_trade(symbol, market_data)
        await alert_generator.on_market_data(symbol, market_data)

    async def on_quote_with_alerts(symbol: str, market_data) -> None:
        """Handle quote data: broadcast to WebSocket AND generate alerts."""
        await broadcast_quote(symbol, market_data)
        await alert_generator.on_market_data(symbol, market_data)

    # Initialize stream manager with combined callbacks
    stream_manager = get_stream_manager()
    stream_manager.set_callbacks(
        on_trade=on_trade_with_alerts,
        on_quote=on_quote_with_alerts,
    )

    # Start alert generator
    try:
        await alert_generator.start()
        logger.info("Alert generator started")
    except Exception as e:
        logger.error(f"Failed to start alert generator: {e}")

    # Start stream manager if credentials are configured (non-fatal if it fails)
    if settings.alpaca_api_key and settings.alpaca_secret_key:
        try:
            await stream_manager.start()
            logger.info("Stream manager started")

            # Auto-subscribe to all watchlist symbols
            try:
                async with async_session_maker() as db:
                    query = select(WatchlistModel).where(WatchlistModel.is_active == True)
                    result = await db.execute(query)
                    watchlist_items = result.scalars().all()
                    symbols = [item.symbol for item in watchlist_items]

                    if symbols:
                        await stream_manager.subscribe(symbols)
                        logger.info(f"Auto-subscribed to {len(symbols)} watchlist symbols: {symbols}")
                    else:
                        logger.info("No symbols in watchlist to auto-subscribe")
            except Exception as e:
                logger.error(f"Failed to auto-subscribe to watchlist: {e}")

        except Exception as e:
            logger.error(f"Failed to start stream manager: {e}")
            logger.warning("Backend will continue without live market data streaming")

    yield

    # Shutdown
    await stream_manager.stop()
    await alert_generator.stop()
    await close_db()


app = FastAPI(
    title=settings.app_name,
    description="Real-time trading alert engine using Alpaca Markets API",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check() -> HealthResponse:
    """Health check endpoint."""
    return HealthResponse(
        status=HealthStatus.HEALTHY,
        timestamp=datetime.utcnow(),
        version="1.0.0",
        database_connected=True,
        alpaca_connected=True,
    )


# Include API router
app.include_router(api_router, prefix="/api/v1")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.is_development,
    )
