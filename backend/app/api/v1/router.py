"""API v1 router aggregator.

The v1 rule-engine routes (`/rules`, `/market-data`) were removed in Phase 3.5 along with
the Alpaca client — the scanner is the only alert source now. `/watchlist` survives as the
optional user favourites list described in `docs/CLAUDE.md` section 5.
"""

from fastapi import APIRouter

from app.api.v1.scanner import router as scanner_router
from app.api.v1.watchlist import router as watchlist_router
from app.api.v1.websocket import router as websocket_router

api_router = APIRouter()

api_router.include_router(scanner_router, prefix="/scanner", tags=["Scanner"])
api_router.include_router(watchlist_router, prefix="/watchlist", tags=["Watchlist"])
api_router.include_router(websocket_router, tags=["WebSocket"])
