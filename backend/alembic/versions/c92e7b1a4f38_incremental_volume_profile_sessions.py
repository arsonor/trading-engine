"""Retain per-session pre-market volume curves

Revision ID: c92e7b1a4f38
Revises: a71f4c9e2d05
Create Date: 2026-08-16 14:22:03.551907

`premarket_volume_profile` stores only `avg_cumulative_volume`. "Add the newest session,
drop the oldest" cannot be done on an average without the departing session's contribution,
and the average is taken PER BUCKET — over the sessions that actually reached that bucket —
so there is not even a single divisor to work backwards from.

This table keeps the curves the average is built from: one row per (ticker, session), a
JSON `bucket_minute -> cumulative_volume` map. ~671 tickers x 20 sessions is about 13,400
rows and ~10 MB.

It also closes one of the three reasons a past session cannot be replayed. The RVOL
denominator's inputs were recomputed nightly and overwritten; now they are kept.

## Downgrade

Drops cleanly — nothing references it, and `premarket_volume_profile` is untouched, so the
scanner keeps working on the averages it already has. What a downgrade costs is the ability
to roll incrementally: the next nightly run reverts to fetching all 20 sessions per ticker,
which is exactly the behaviour that existed before this revision.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from app.core.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = 'c92e7b1a4f38'
down_revision: Union[str, Sequence[str], None] = 'a71f4c9e2d05'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "premarket_session_volume",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        # JSON object keys are strings on the way back out; PremarketSessionVolume
        # .bucket_map() is the reader that undoes that.
        sa.Column("buckets", sa.JSON(), nullable=False),
        sa.Column("bars_used", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("computed_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["ticker"], ["universe.ticker"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker", "session_date", name="uq_premarket_session_volume_ticker_date"
        ),
    )
    op.create_index(
        op.f("ix_premarket_session_volume_id"), "premarket_session_volume", ["id"]
    )
    op.create_index(
        op.f("ix_premarket_session_volume_ticker"), "premarket_session_volume", ["ticker"]
    )
    op.create_index(
        op.f("ix_premarket_session_volume_session_date"),
        "premarket_session_volume",
        ["session_date"],
    )

    # Without this the table is readable AND writable through Supabase's Data API by
    # anyone holding the anon key. tests/integration/test_rls.py enforces it.
    enable_rls("premarket_session_volume")


def downgrade() -> None:
    """Drop the table. The profile averages survive; only incremental rebuilds are lost."""
    op.drop_index(
        op.f("ix_premarket_session_volume_session_date"), table_name="premarket_session_volume"
    )
    op.drop_index(
        op.f("ix_premarket_session_volume_ticker"), table_name="premarket_session_volume"
    )
    op.drop_index(op.f("ix_premarket_session_volume_id"), table_name="premarket_session_volume")
    op.drop_table("premarket_session_volume")
