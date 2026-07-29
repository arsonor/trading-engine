"""Alert database model — the v2 scanner contract.

The retained v1 columns (`rule_id`, `setup_type`, `entry_price`, `stop_loss`,
`target_price`, `market_data_json`) and the FK to `rules` were removed in Phase 3.5,
along with the rule engine that populated them.

`ticker` is the storage column name as well as the API field name. It was `symbol` while
the v1 tables still used that convention; the storage/API mapping layer that bridged the
two is gone.

**`upside_pct` and `nearest_resistance` are nullable by design.** Stage 3 currently
rejects tickers trading above all four resistance levels, so today they are always
populated — but that rejection is a deferred strategy decision (see `docs/CLAUDE.md` 4.3
"Breakout convention"). Keeping the columns nullable is what makes reversing it a
one-branch change instead of a migration.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class Alert(Base):
    """A pre-market scanner alert (`docs/CLAUDE.md` section 4.4)."""

    __tablename__ = "alerts"
    __table_args__ = (
        # Dedup: one alert per ticker per session, updated in place by later scans.
        UniqueConstraint("ticker", "session_date", name="uq_alerts_ticker_session"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    scan_run_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("scan_runs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # ET trading session this alert belongs to. The dedup key, and the reason a scan at
    # 04:05 and one at 09:25 update one row rather than producing two alerts.
    session_date: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    # Threshold profile that produced it. Stamped so demo output is never mistakable
    # for real output, at every layer down to the row.
    profile: Mapped[str | None] = mapped_column(String(30), nullable=True, index=True)

    gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    rvol_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    rvol_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rvol_is_approximate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    catalyst: Mapped[str | None] = mapped_column(String(255), nullable=True)
    entry_reference_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    # Nullable by design — see the module docstring.
    nearest_resistance: Mapped[float | None] = mapped_column(Float, nullable=True)
    resistance_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    upside_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    suggested_entry_window: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scan_timestamp: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    is_final_pass: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    score_breakdown_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    @property
    def is_demo(self) -> bool:
        """Whether this alert came from a loosened demo profile."""
        return self.profile is not None and self.profile != "production"

    def __repr__(self) -> str:
        return (
            f"<Alert(id={self.id}, ticker={self.ticker}, profile={self.profile}, "
            f"score={self.confidence_score})>"
        )
