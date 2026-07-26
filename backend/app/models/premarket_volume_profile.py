"""Pre-market volume profile model (v2 scanner).

Schema only in V1. Populating it requires `extended=true` intraday bars (pre/after-market
intervals), which FMP support confirmed is Premium-only — see `docs/PLAN.md`. The
time-of-day-normalized RVOL that consumes this table therefore lands in app V3.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PremarketVolumeProfile(Base):
    """Average cumulative pre-market volume per 5-minute bucket from 04:00 ET."""

    __tablename__ = "premarket_volume_profile"
    __table_args__ = (
        UniqueConstraint("ticker", "bucket_minute", name="uq_premarket_profile_ticker_bucket"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("universe.ticker", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Minutes elapsed since 04:00 ET (0, 5, 10, ... 325 for the 09:25 cutoff).
    bucket_minute: Mapped[int] = mapped_column(Integer, nullable=False)
    avg_cumulative_volume: Mapped[float] = mapped_column(Float, nullable=False)
    sessions_sampled: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    computed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    def __repr__(self) -> str:
        return (
            f"<PremarketVolumeProfile(ticker={self.ticker}, bucket={self.bucket_minute}, "
            f"avg={self.avg_cumulative_volume})>"
        )
