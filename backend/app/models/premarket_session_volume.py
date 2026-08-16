"""One session's pre-market volume curve, retained so the profile can roll incrementally.

## Why this table has to exist

`premarket_volume_profile` stores only `avg_cumulative_volume` — the average. "Add the
newest session, drop the oldest" is arithmetic you cannot do on an average without knowing
what the oldest session contributed, and nothing retained it. Worse, the average is taken
**per bucket**, over the sessions that actually reached that bucket, so there is not even a
single session count to work backwards from: bucket 0 may be an average of 8 sessions while
bucket 300 is an average of 20.

So a genuinely incremental rebuild needs the per-session curves kept. That is this table.

## The second reason, which outlives the first

These curves are the RVOL **denominator's** history. Until now they were recomputed nightly
and overwritten, which is one of the three reasons a past session cannot be replayed —
alongside upward bar revisions and `reference_data` being upserted in place. Keeping them
closes that one. `scan_observations` copies the denominator that was *used*; this keeps the
inputs it was built from.

## Shape

One row per (ticker, session), holding a bucket→cumulative-volume map. ~671 tickers × 20
sessions ≈ 13,400 rows, about 10 MB — against ~886,000 rows for a row-per-bucket layout
that nothing currently needs to query that way. Dropping a session out of the window is a
DELETE by date.

**JSON object keys are strings.** `buckets` round-trips as `{"0": 1200.0}`, not
`{0: 1200.0}`, and code reading it must convert. `bucket_map()` is the only sanctioned
reader for that reason.
"""

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PremarketSessionVolume(Base):
    """The cumulative pre-market volume curve for one ticker on one session."""

    __tablename__ = "premarket_session_volume"
    __table_args__ = (
        UniqueConstraint(
            "ticker", "session_date", name="uq_premarket_session_volume_ticker_date"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    ticker: Mapped[str] = mapped_column(
        String(16),
        ForeignKey("universe.ticker", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    session_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)

    # {bucket_minute: cumulative_volume}, minutes elapsed since 04:00 ET. Stored as JSON
    # so one session is one row; see the module docstring on string keys.
    buckets: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    # How many settled bars this curve was built from — the audit trail for a thin session.
    bars_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    computed_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    def bucket_map(self) -> dict[int, float]:
        """`buckets` with integer keys — the only sanctioned way to read it.

        JSON object keys are strings, so a caller doing `row.buckets[0]` gets a KeyError
        while `row.buckets["0"]` works, and averaging over the raw dict would silently
        produce a profile keyed by strings that never matches a live bucket lookup.
        """
        return {int(bucket): float(value) for bucket, value in (self.buckets or {}).items()}

    def __repr__(self) -> str:
        return (
            f"<PremarketSessionVolume(ticker={self.ticker}, session={self.session_date}, "
            f"buckets={len(self.buckets or {})})>"
        )
