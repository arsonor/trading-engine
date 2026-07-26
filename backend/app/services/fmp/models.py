"""Typed FMP response models.

Shapes follow the documented `stable/` endpoints. Every model is permissive about
*extra* fields (FMP adds them without notice) and strict about the fields we actually
compute from — a silently missing `close` would poison every derived metric.
"""

from datetime import date as date_type

from pydantic import BaseModel, ConfigDict, Field, field_validator


class FmpModel(BaseModel):
    """Base: ignore unknown fields, keep declared ones honest."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class EodBar(FmpModel):
    """One daily bar from `historical-price-eod/full`."""

    symbol: str | None = None
    date: date_type
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float | None = None
    change: float | None = None
    change_percent: float | None = Field(default=None, alias="changePercent")

    @field_validator("date", mode="before")
    @classmethod
    def parse_date(cls, v):
        """FMP returns 'YYYY-MM-DD', occasionally with a time suffix."""
        if isinstance(v, str):
            return date_type.fromisoformat(v[:10])
        return v


class SharesFloat(FmpModel):
    """Response from `shares-float`.

    Every numeric field is optional: FMP has no float for some symbols, and a missing
    float must stay missing rather than defaulting to something that passes Stage 1.
    """

    symbol: str
    date: str | None = None
    free_float: float | None = Field(default=None, alias="freeFloat")
    float_shares: float | None = Field(default=None, alias="floatShares")
    outstanding_shares: float | None = Field(default=None, alias="outstandingShares")


class Quote(FmpModel):
    """Snapshot from `quote` / `batch-quote`."""

    symbol: str
    name: str | None = None
    price: float | None = None
    change: float | None = None
    change_percentage: float | None = Field(default=None, alias="changePercentage")
    volume: float | None = None
    previous_close: float | None = Field(default=None, alias="previousClose")
    day_low: float | None = Field(default=None, alias="dayLow")
    day_high: float | None = Field(default=None, alias="dayHigh")
    market_cap: float | None = Field(default=None, alias="marketCap")
    exchange: str | None = None
    timestamp: int | None = None


class CompanyProfile(FmpModel):
    """Response from `profile`."""

    symbol: str
    company_name: str | None = Field(default=None, alias="companyName")
    exchange: str | None = None
    exchange_full_name: str | None = Field(default=None, alias="exchangeFullName")
    sector: str | None = None
    industry: str | None = None
    market_cap: float | None = Field(default=None, alias="marketCap")
    price: float | None = None
    is_actively_trading: bool | None = Field(default=None, alias="isActivelyTrading")
