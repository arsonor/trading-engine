"""API v1 router aggregator."""

from fastapi import APIRouter

from app.api.v1.alerts import router as alerts_router
from app.api.v1.market_data import router as market_data_router
from app.api.v1.rules import router as rules_router
from app.api.v1.watchlist import router as watchlist_router
from app.api.v1.websocket import router as websocket_router

api_router = APIRouter()

api_router.include_router(alerts_router, prefix="/alerts", tags=["Alerts"])
api_router.include_router(rules_router, prefix="/rules", tags=["Rules"])
api_router.include_router(watchlist_router, prefix="/watchlist", tags=["Watchlist"])
api_router.include_router(market_data_router, prefix="/market-data", tags=["Market Data"])
api_router.include_router(websocket_router, tags=["WebSocket"])
