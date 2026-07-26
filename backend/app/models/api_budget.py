"""Daily FMP API budget model.

The free tier stops at 250 calls/day with a hard 429 and no overage. The counter has to
survive process restarts, so it lives in the database rather than in memory.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ApiBudget(Base):
    """Calls consumed per UTC day, per provider."""

    __tablename__ = "api_budget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # UTC date. FMP's quota resets at 00:00 UTC, so the key is deliberately not ET.
    budget_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="fmp")
    calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return f"<ApiBudget(date={self.budget_date}, calls_used={self.calls_used})>"
