"""FastAPI application entry point."""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.api.v1.websocket import get_manager
from app.config import get_settings
from app.core.database import close_db, init_db
from app.schemas import HealthResponse, HealthStatus
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

    # Initialize stream manager with callbacks
    stream_manager = get_stream_manager()
    stream_manager.set_callbacks(
        on_trade=broadcast_trade,
        on_quote=broadcast_quote,
    )

    # Start stream manager if credentials are configured
    if settings.alpaca_api_key and settings.alpaca_secret_key:
        await stream_manager.start()
        logger.info("Stream manager started")

    yield

    # Shutdown
    await stream_manager.stop()
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
