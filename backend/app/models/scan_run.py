"""Scan-run observability model (v2 scanner).

A failed scan and a scan that legitimately found nothing must never look the same —
in the DB or in the UI. That distinction lives in `status` + `stage_counts_json`.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ScanRunStatus:
    """Allowed values for `ScanRun.status` (kept as constants, not a DB enum)."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    # Woke up outside the 04:00-09:25 ET window and did no work. Distinct from both
    # "completed with zero candidates" and "failed".
    SKIPPED = "skipped"


class ScanRun(Base):
    """One execution of the scanner pipeline."""

    __tablename__ = "scan_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ScanRunStatus.RUNNING, index=True
    )
    # Threshold profile ("production" / "demo"). Stamped on every run so demo output can
    # never be mistaken for real output. Consumed from Phase 2.
    profile: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # What this run was permitted to write: live | observation | dry_run.
    #
    # Needed because "no alerts" is ambiguous without it. A run that produced none because
    # it was in observation mode and one that produced none because the market was quiet
    # look identical from the alert count alone — the same trap the design already avoids
    # for failed-scan versus quiet-market. Nullable: rows written before this column
    # existed cannot have their mode reconstructed, and guessing "live" for them would be
    # a fabrication.
    mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stage_counts_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    api_calls_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<ScanRun(id={self.id}, status={self.status}, profile={self.profile})>"
