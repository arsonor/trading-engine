"""Phase 6: scan_observations, the decision-time evidence table

Revision ID: a71f4c9e2d05
Revises: 3d1177ad1103
Create Date: 2026-08-16 09:40:12.114208

One row per (scan_run, ticker) holding what the scanner saw about that ticker on that
pass: the Stage-2 inputs and outputs, the stage it reached, why it stopped, and — copied,
not joined — the reference values that were its denominators.

## Why the denominators are duplicated onto every row

`reference_data` is one current row per ticker, upserted nightly, and
`premarket_volume_profile` is unique per `(ticker, bucket_minute)` and rebuilt nightly.
Joining to either at read time would answer with tonight's numbers rather than the ones
the decision was made from — precisely the bug this table exists to prevent. Phase 4A also
measured 49.4% of pre-market bars revised upward within ~7 minutes of closing, so
re-fetching the bars does not recover it either.

## Why it is worth a table

Phase 6 commits to a threshold sensitivity sweep over 3% / 15% / 10% / 5.5%. That is a
question about the tickers the scanner REJECTED, and `stage_counts_json` stores rejections
as `{ticker, stage, reason}` with no values. The question is currently unanswerable at any
scan cadence, and every session that passes without this table is evidence gone for good.

## Downgrade

`op.drop_table` is clean — nothing references `scan_observations`, and its own FK to
`scan_runs` is ON DELETE CASCADE, so dropping it cannot orphan anything. The data is not
recoverable afterwards for the reasons above, which makes the downgrade a one-way door for
the rows even though the schema round-trips exactly.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from app.core.rls import enable_rls

# revision identifiers, used by Alembic.
revision: str = 'a71f4c9e2d05'
down_revision: Union[str, Sequence[str], None] = '3d1177ad1103'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "scan_observations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scan_run_id", sa.Integer(), nullable=False),
        sa.Column("session_date", sa.Date(), nullable=False),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("is_final_pass", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ticker", sa.String(length=16), nullable=False),
        # Outcome.
        sa.Column("stage_reached", sa.String(length=32), nullable=False),
        sa.Column("rejection_reason", sa.String(length=80), nullable=True),
        sa.Column("rejection_detail", sa.String(length=255), nullable=True),
        sa.Column("is_candidate", sa.Boolean(), nullable=False, server_default=sa.false()),
        # Stage 2. All nullable: the stages short-circuit, so NULL means NOT EVALUATED
        # rather than zero, and a sweep has to treat the two differently.
        sa.Column("price_premarket_current", sa.Float(), nullable=True),
        sa.Column("volume_premarket_accumulated", sa.Float(), nullable=True),
        sa.Column("gap_pct", sa.Float(), nullable=True),
        sa.Column("rvol_pct", sa.Float(), nullable=True),
        sa.Column("rvol_mode", sa.String(length=20), nullable=True),
        sa.Column(
            "rvol_is_approximate", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        # Decision-time provenance.
        sa.Column("bars_settled_through", sa.DateTime(), nullable=True),
        sa.Column("provisional_bars_excluded", sa.Integer(), nullable=True),
        sa.Column("profile_sessions_sampled", sa.Integer(), nullable=True),
        sa.Column("snapshot_source", sa.String(length=20), nullable=True),
        # The denominators, copied not joined.
        sa.Column("static_float", sa.BigInteger(), nullable=True),
        sa.Column("volume_avg_20d", sa.Float(), nullable=True),
        sa.Column("price_close_yesterday", sa.Float(), nullable=True),
        sa.Column("high_yesterday", sa.Float(), nullable=True),
        sa.Column("high_20d", sa.Float(), nullable=True),
        sa.Column("sma_50", sa.Float(), nullable=True),
        sa.Column("sma_200", sa.Float(), nullable=True),
        # Stage 3.
        sa.Column("nearest_resistance", sa.Float(), nullable=True),
        sa.Column("resistance_source", sa.String(length=30), nullable=True),
        sa.Column("upside_pct", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["scan_run_id"], ["scan_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("scan_run_id", "ticker", name="uq_scan_observation_run_ticker"),
    )
    op.create_index(op.f("ix_scan_observations_id"), "scan_observations", ["id"])
    op.create_index(
        op.f("ix_scan_observations_scan_run_id"), "scan_observations", ["scan_run_id"]
    )
    op.create_index(
        op.f("ix_scan_observations_session_date"), "scan_observations", ["session_date"]
    )
    op.create_index(op.f("ix_scan_observations_ticker"), "scan_observations", ["ticker"])
    op.create_index(
        op.f("ix_scan_observations_stage_reached"), "scan_observations", ["stage_reached"]
    )
    # The sweep's access pattern: one session, every observation, filtered on values.
    op.create_index(
        "ix_scan_observations_session", "scan_observations", ["session_date", "stage_reached"]
    )
    op.create_index(
        "ix_scan_observations_ticker_session", "scan_observations", ["ticker", "session_date"]
    )

    # Without this the table is readable AND writable through Supabase's Data API by
    # anyone holding the anon key. tests/integration/test_rls.py enforces it.
    enable_rls("scan_observations")


def downgrade() -> None:
    """Drop the table. See the module docstring: the schema round-trips, the data does not."""
    op.drop_index("ix_scan_observations_ticker_session", table_name="scan_observations")
    op.drop_index("ix_scan_observations_session", table_name="scan_observations")
    op.drop_index(op.f("ix_scan_observations_stage_reached"), table_name="scan_observations")
    op.drop_index(op.f("ix_scan_observations_ticker"), table_name="scan_observations")
    op.drop_index(op.f("ix_scan_observations_session_date"), table_name="scan_observations")
    op.drop_index(op.f("ix_scan_observations_scan_run_id"), table_name="scan_observations")
    op.drop_index(op.f("ix_scan_observations_id"), table_name="scan_observations")
    op.drop_table("scan_observations")
