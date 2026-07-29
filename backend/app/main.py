"""FastAPI application entry point.

The v2 app is alerts-only and has no live market-data stream: candidates are produced by
the scheduled pre-market scanner (`scripts/run_scan.py`, run by Render cron), which
persists alerts and pushes them over the WebSocket. Nothing in this process talks to a
market-data provider — the Alpaca client, stream manager and per-tick rule engine were
removed in Phase 3.5.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import get_settings
from app.core.database import check_db_connectivity, close_db, init_db
from app.schemas import HealthResponse, HealthStatus

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    await init_db()
    logger.info("API ready — alerts are produced by the scheduled scanner, not by this process.")
    yield
    await close_db()


app = FastAPI(
    title=settings.app_name,
    description=(
        "Alerts-only pre-market stock scanner. Surfaces candidates where a ~5% intraday "
        "move is structurally plausible. Does not execute trades and is not financial advice."
    ),
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
    """Health check endpoint. Reports DB connectivity as a real probe."""
    db_ok = await check_db_connectivity()
    return HealthResponse(
        status=HealthStatus.HEALTHY if db_ok else HealthStatus.UNHEALTHY,
        timestamp=datetime.utcnow(),
        version="1.0.0",
        database_connected=db_ok,
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
