"""Watchlist Pydantic schemas."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class WatchlistBase(BaseModel):
    """Base watchlist schema."""

    symbol: str = Field(..., min_length=1, max_length=10)
    notes: Optional[str] = Field(None, max_length=500)


class WatchlistCreate(WatchlistBase):
    """Schema for adding to watchlist."""

    pass


class WatchlistItem(WatchlistBase):
    """Watchlist item response schema."""

    id: int
    added_at: datetime
    is_active: bool

    class Config:
        from_attributes = True
