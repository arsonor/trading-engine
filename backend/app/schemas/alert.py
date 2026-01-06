"""Alert Pydantic schemas."""

from datetime import datetime
from enum import Enum
from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class SetupType(str, Enum):
    """Alert setup types."""

    BREAKOUT = "breakout"
    VOLUME_SPIKE = "volume_spike"
    GAP_UP = "gap_up"
    GAP_DOWN = "gap_down"
    MOMENTUM = "momentum"


class AlertMarketData(BaseModel):
    """Market data snapshot when alert was triggered."""

    price: Optional[float] = None
    volume: Optional[int] = None
    volume_ratio: Optional[float] = Field(None, description="Current volume / average volume")
    day_high: Optional[float] = None
    day_low: Optional[float] = None
    pre_market_high: Optional[float] = None
    float_shares: Optional[int] = Field(None, description="Number of shares available for trading")
    short_interest: Optional[float] = Field(None, description="Short interest ratio")


class AlertBase(BaseModel):
    """Base alert schema."""

    symbol: str = Field(..., max_length=10)
    timestamp: datetime
    setup_type: SetupType
    entry_price: float
    stop_loss: Optional[float] = None
    target_price: Optional[float] = None
    confidence_score: Optional[float] = Field(None, ge=0, le=1)
    market_data: Optional[AlertMarketData] = None


class AlertCreate(AlertBase):
    """Schema for creating an alert."""

    rule_id: Optional[int] = None


class AlertUpdate(BaseModel):
    """Schema for updating an alert."""

    is_read: Optional[bool] = None


class Alert(AlertBase):
    """Alert response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    rule_id: Optional[int] = None
    rule_name: Optional[str] = None
    is_read: bool
    created_at: datetime


class AlertListResponse(BaseModel):
    """Paginated alert list response."""

    items: list[Alert]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_prev: bool


class AlertStats(BaseModel):
    """Alert statistics response."""

    total_alerts: int
    alerts_today: int
    unread_count: int
    by_setup_type: Dict[str, int] = {}
    by_symbol: Dict[str, int] = {}
    avg_confidence: Optional[float] = None
