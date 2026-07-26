"""Universe database model (v2 scanner).

Naming note: v2 scanner tables use `ticker` (per `docs/CLAUDE.md` sections 4.4 and 5),
while the retained v1 tables (`alerts`, `watchlist`) keep their original `symbol` column.
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Universe(Base):
    """A ticker the scanner may consider.

    `is_accessible_free_tier` is populated empirically by `scripts/probe_fmp_symbols.py`
    rather than assumed from FMP's documentation — the free tier's symbol sample is
    discovered, not declared. The accessible subset IS the V1 universe.
    """

    __tablename__ = "universe"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, index=True)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    exchange: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Free-tier probe results. NULL = never probed.
    is_accessible_free_tier: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    probe_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_probed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    last_refreshed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<Universe(ticker={self.ticker}, is_active={self.is_active}, "
            f"accessible={self.is_accessible_free_tier})>"
        )
