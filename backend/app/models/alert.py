"""Alert database model.

This table is *extended* rather than replaced, per `docs/CLAUDE.md` section 5. The v1
columns (`setup_type`, `entry_price`, `stop_loss`, `target_price`, `rule_id`) are kept so
the v1 rule-engine path and its tests keep working until Alpaca is removed in its own
commit; they are nullable now, because a v2 scanner alert has no honest value for them.

Column naming: v2 tables use `ticker`, retained v1 tables use `symbol`. This table keeps
`symbol` as the storage column (it is the ticker) and the API exposes it as `ticker` to
match the section 4.4 alert contract. The mapping lives in `app/schemas/scanner.py`.

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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Alert(Base):
    """Trading alert — v2 scanner contract plus retained v1 columns."""

    __tablename__ = "alerts"
    __table_args__ = (
        # Dedup: one alert per ticker per session, updated in place by later scans.
        # Partial index so v1 rule-engine alerts (session_date NULL) are unaffected.
        UniqueConstraint("symbol", "session_date", name="uq_alerts_symbol_session"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    symbol: Mapped[str] = mapped_column(String(10), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    confidence_score: Mapped[float | None] = mapped_column(Float, nullable=True, index=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # --- v2 scanner contract (docs/CLAUDE.md 4.4) --------------------------------
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

    # --- retained v1 columns (nullable; rule-engine path only) --------------------
    rule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("rules.id", ondelete="SET NULL"), nullable=True
    )
    setup_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    stop_loss: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    market_data_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    rule: Mapped["Rule"] = relationship("Rule", back_populates="alerts")

    @property
    def is_demo(self) -> bool:
        """Whether this alert came from a loosened demo profile."""
        return self.profile is not None and self.profile != "production"

    def __repr__(self) -> str:
        return (
            f"<Alert(id={self.id}, symbol={self.symbol}, profile={self.profile}, "
            f"score={self.confidence_score})>"
        )


# Import Rule here to avoid circular imports
from app.models.rule import Rule  # noqa: E402, F401
