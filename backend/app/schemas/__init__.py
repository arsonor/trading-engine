"""Pydantic schemas."""

from app.schemas.alert import (
    Alert,
    AlertCreate,
    AlertListResponse,
    AlertMarketData,
    AlertStats,
    AlertUpdate,
    SetupType,
)
from app.schemas.common import ErrorResponse, HealthResponse, HealthStatus
from app.schemas.market_data import Bar, MarketData, Timeframe
from app.schemas.rule import Rule, RuleCreate, RuleType, RuleUpdate
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
    # Alert
    "Alert",
    "AlertCreate",
    "AlertListResponse",
    "AlertMarketData",
    "AlertStats",
    "AlertUpdate",
    "SetupType",
    # Common
    "ErrorResponse",
    "HealthResponse",
    "HealthStatus",
    # Market Data
    "Bar",
    "MarketData",
    "Timeframe",
    # Rule
    "Rule",
    "RuleCreate",
    "RuleType",
    "RuleUpdate",
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
