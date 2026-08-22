"""What the scanner saw about one ticker on one pass — the Phase 5 evidence table.

## Why this exists

`scan_runs.stage_counts_json` records candidates as bare ticker strings and rejections as
`{ticker, stage, reason}` with no numbers. So the scanner has always recorded *that* a
ticker was rejected at Stage 2 and never *what its gap and RVOL were*. Phase 5 commits to
a **threshold sensitivity sweep** — justifying or revising 3% / 15% / 10% / 5.5% — and
that question cannot be asked of the data as stored, at any scan cadence.

## Why it cannot be backfilled

Re-fetching does not recover it, for three independent reasons:

1. Phase 4A measured **49.4% of pre-market bars revised upward** within ~7 minutes of
   closing (worst case +7,156%). Settled history is not what the scanner decided on, so a
   replay over it would "detect" candidates nothing could have seen.
2. `reference_data` is one current row per ticker, upserted nightly. That morning's float,
   20-day average volume and 20-day high are gone.
3. `premarket_volume_profile` is unique per `(ticker, bucket_minute)` and rebuilt nightly,
   so the normalized-RVOL denominator is gone too.

The denominators are therefore **copied onto every row** rather than joined to at read
time. That is deliberate duplication: a join to `reference_data` would silently answer
with tonight's numbers, which is precisely the bug this table exists to prevent.

Every session that runs without this is evidence gone for good. That is the whole argument
for its priority.

## What gets written, and when

Writing all ~741 Stage-1 survivors on all 66 passes would be ~12M rows a year for almost
no gain — consecutive passes are near-duplicates (measured: 0.2-0.6 new tickers per pass
through the early session). So:

- **the authoritative 09:25 pass** writes every Stage-1 survivor, which is what makes a
  sweep over the true rejected population possible;
- **anchor passes** (04:15, 07:00, 08:30 by default) write candidates only, so
  early-versus-late detection stays answerable;
- every other pass writes nothing.

~185k + ~15k rows a year, about 21 MB. Retention is indefinite by decision (15 August
2026); revisit before that stops being true rather than after.
"""

from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ScanObservation(Base):
    """One ticker's decision-time state on one scan pass."""

    __tablename__ = "scan_observations"
    __table_args__ = (
        # One row per ticker per pass. A retried write converges instead of duplicating.
        UniqueConstraint("scan_run_id", "ticker", name="uq_scan_observation_run_ticker"),
        # The sweep's access pattern: one session, every observation, filtered on values.
        Index("ix_scan_observations_session", "session_date", "stage_reached"),
        Index("ix_scan_observations_ticker_session", "ticker", "session_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    scan_run_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # The ET moment the pass decided on, stored naive — same convention as
    # `alerts.scan_timestamp`, which is `as_of_et` with the tzinfo dropped.
    observed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    is_final_pass: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # No FK to `universe`: this is a historical record, and a delisted ticker leaving the
    # universe must not cascade away the evidence of what it did last March.
    ticker: Mapped[str] = mapped_column(String(16), nullable=False, index=True)

    # --- Outcome -----------------------------------------------------------------
    # The stage this ticker reached: the one it was rejected at, or `risk_filters` when it
    # survived everything. `rejection_reason` is NULL exactly when `is_candidate` is true.
    stage_reached: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(80), nullable=True)
    rejection_detail: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_candidate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- Stage 2 inputs and outputs ----------------------------------------------
    # All nullable: the stages short-circuit, so a ticker rejected on gap never has RVOL
    # computed. NULL here means "never evaluated", which is itself a fact about the pass
    # and must not be confused with zero. See `sweep_limitations` in the writer.
    price_premarket_current: Mapped[float | None] = mapped_column(Float, nullable=True)
    volume_premarket_accumulated: Mapped[float | None] = mapped_column(Float, nullable=True)
    gap_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    rvol_pct: Mapped[float | None] = mapped_column(Float, nullable=True)
    rvol_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    rvol_is_approximate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # --- Decision-time provenance (Phase 4C fields, per observation) --------------
    bars_settled_through: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    provisional_bars_excluded: Mapped[int | None] = mapped_column(Integer, nullable=True)
    profile_sessions_sampled: Mapped[int | None] = mapped_column(Integer, nullable=True)
    snapshot_source: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # --- The denominators, copied not joined -------------------------------------
    # See the module docstring: `reference_data` is overwritten nightly, so joining to it
    # later would answer with numbers that did not exist at decision time.
    static_float: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    volume_avg_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_close_yesterday: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_yesterday: Mapped[float | None] = mapped_column(Float, nullable=True)
    high_20d: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma_50: Mapped[float | None] = mapped_column(Float, nullable=True)
    sma_200: Mapped[float | None] = mapped_column(Float, nullable=True)

    # --- Stage 3 ------------------------------------------------------------------
    nearest_resistance: Mapped[float | None] = mapped_column(Float, nullable=True)
    resistance_source: Mapped[str | None] = mapped_column(String(30), nullable=True)
    upside_pct: Mapped[float | None] = mapped_column(Float, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    def __repr__(self) -> str:
        return (
            f"<ScanObservation(ticker={self.ticker}, session={self.session_date}, "
            f"stage={self.stage_reached}, gap={self.gap_pct})>"
        )
