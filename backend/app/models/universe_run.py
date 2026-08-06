"""Universe build history.

**The Stage-1 universe size is discovered, never configured.** Phase 4A measured 554
tickers, but that is one day's output of a filter that moves with price, 20-day volume,
float revisions, listings and delistings — and moves *immediately* the moment the end user
edits a threshold in the dashboard.

This table exists so that movement is visible. Without a record of what the size was
yesterday, a threshold edit that quadruples the universe looks exactly like a normal night:
the build succeeds, the scan runs, and the only symptom is that passes stop finishing
inside the 5-minute cadence. 4A projected that bandwidth becomes a real constraint past
roughly 3,500 tickers, which a single careless edit can cross.

So each build records its own count and compares against the trailing median of previous
builds. `warning` is set — not raised — when the size moves materially or crosses the
configured ceiling: a surprising universe is a thing to look at, not a reason to leave the
scanner without data.
"""

from datetime import datetime

from sqlalchemy import BigInteger, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UniverseRunStatus:
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class UniverseRun(Base):
    """One execution of the two-step universe build."""

    __tablename__ = "universe_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=UniverseRunStatus.RUNNING
    )

    # Step 1: the over-inclusive screener pre-filter.
    screener_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Step 2: rows returned by bulk float.
    float_rows: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The maintained set: tickers we keep reference_data for. Nightly EOD cost scales
    # with this.
    universe_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The subset that currently clears the PRODUCTION Stage-1 filters (float and 20-day
    # volume) against existing reference_data. This — not `universe_size` — is what the
    # live scan walks on every 5-minute pass, so it is the number 4A's bandwidth ceiling
    # actually describes. Nullable because it cannot be computed before the first
    # reference_data refresh.
    stage1_eligible: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Churn, so a large swing can be explained rather than merely noticed.
    activated: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deactivated: Mapped[int | None] = mapped_column(Integer, nullable=True)

    calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bytes_used: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)

    # Set when the size moved materially or crossed the ceiling. Not an error.
    warning: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<UniverseRun(id={self.id}, status={self.status}, "
            f"universe_size={self.universe_size})>"
        )
