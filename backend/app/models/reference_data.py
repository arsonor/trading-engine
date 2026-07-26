"""Reference-data database model (v2 scanner).

One current row per ticker, upserted by the nightly reference pipeline. Everything here
is derived from end-of-day data so the morning scan never has to recompute it — that is
what makes a universe-wide scan fit inside the FMP rate limit.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ReferenceData(Base):
    """Pre-computed per-ticker reference metrics used by Stage 1 and Stage 3."""

    __tablename__ = "reference_data"
    __table_args__ = (
        # Stage 1 filters on float + average volume; this index serves that query.
        Index("ix_reference_data_stage1", "static_float", "volume_avg_20d"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("universe.ticker", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )

    # Float is null-tolerant on purpose: FMP does not have it for every symbol, and a
    # missing float must not silently become a passing Stage-1 candidate.
    static_float: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    outstanding_shares: Mapped[int | None] = mapped_column(BigInteger, nullable=True)

    volume_avg_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_close_yesterday: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_yesterday: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma_50: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma_200: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Provenance — needed to tell "computed from real EOD data" from "fixture replay".
    last_bar_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    bars_used: Mapped[int | None] = mapped_column(Integer, nullable=True)
    data_source: Mapped[str] = mapped_column(String(20), nullable=False, default="fmp")

    computed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )

    def __repr__(self) -> str:
        return (
            f"<ReferenceData(ticker={self.ticker}, float={self.static_float}, "
            f"avg_vol_20d={self.volume_avg_20d})>"
        )
