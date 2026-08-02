"""API v1 router aggregator.

Only the scanner and the client WebSocket remain. The v1 rule-engine routes (`/rules`,
`/market-data`, `/alerts`) went with the Alpaca client in Phase 3.5, and `/watchlist`
followed once it had no UI and no place in the v2 spec.
"""

from fastapi import APIRouter

from app.api.v1.scanner import router as scanner_router
from app.api.v1.websocket import router as websocket_router

api_router = APIRouter()

api_router.include_router(scanner_router, prefix="/scanner", tags=["Scanner"])
api_router.include_router(websocket_router, tags=["WebSocket"])
