"""Daily FMP API usage model.

Originally a call counter: the free tier stopped at 250 calls/day with a hard 429, so the
count had to survive process restarts and therefore lives in the database.

**Premium changed what is scarce.** There is no daily call cap — the limits are 750
calls/minute and 50 GB per rolling 30 days. Phase 4A measured that a full session of live
scanning costs ~0.35 GB, so **bytes are now the binding constraint and calls are not**.
`bytes_used` is tracked for that reason: the call ceiling survives only as runaway
protection, while bandwidth is the number that can actually end the month early.
"""

from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ApiBudget(Base):
    """Calls and bytes consumed per UTC day, per provider."""

    __tablename__ = "api_budget"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # UTC date. FMP's quota resets at 00:00 UTC, so the key is deliberately not ET.
    budget_date: Mapped[date] = mapped_column(Date, nullable=False, unique=True, index=True)
    provider: Mapped[str] = mapped_column(String(20), nullable=False, default="fmp")
    calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # BigInteger, not Integer: a single session moves ~0.35 GB, so a busy month passes
    # 2^31 bytes comfortably and would silently overflow a 32-bit column.
    bytes_used: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<ApiBudget(date={self.budget_date}, calls_used={self.calls_used}, "
            f"bytes_used={self.bytes_used})>"
        )
