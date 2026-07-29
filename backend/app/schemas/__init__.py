"""Pydantic schemas.

The v1 alert schema (`setup_type`, `entry_price`, `stop_loss`, `target_price`) was
removed in Phase 3.5 along with the rule engine that produced it. The v2 alert contract
lives in `app/schemas/scanner.py` and is documented in `docs/CLAUDE.md` section 4.4.
"""

from app.schemas.common import ErrorResponse, HealthResponse, HealthStatus
from app.schemas.scanner import (
    ScannerAlert,
    ScannerAlertListResponse,
    ScannerStatus,
    ScanRunOut,
    ScoreBreakdownOut,
    ScoreFactorOut,
    ThresholdSettings,
    ThresholdSettingsUpdate,
)
from app.schemas.watchlist import WatchlistCreate, WatchlistItem

__all__ = [
    # Common
    "ErrorResponse",
    "HealthResponse",
    "HealthStatus",
    # Scanner (v2)
    "ScanRunOut",
    "ScannerAlert",
    "ScannerAlertListResponse",
    "ScannerStatus",
    "ScoreBreakdownOut",
    "ScoreFactorOut",
    "ThresholdSettings",
    "ThresholdSettingsUpdate",
    # Watchlist
    "WatchlistCreate",
    "WatchlistItem",
]
