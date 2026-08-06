"""Phase 4B: bandwidth tracking and universe run history

Revision ID: b008d4bf3a18
Revises: 9c3b774f629a
Create Date: 2026-08-06 15:27:48.417942

Two additions, both driven by what Phase 4A measured about Premium.

**`api_budget.bytes_used`** — Premium has no daily call cap; the limits are 750 calls/minute
and 50 GB per rolling 30 days. A full session of live scanning moves ~0.35 GB, so bytes are
the constraint that can actually end a month early while the call counter sits comfortably
mid-range. Added with `server_default='0'`, so it is safe on a populated `api_budget`
without a backfill step.

**`universe_runs`** — the Stage-1 universe size is discovered nightly, never configured.
Recording it is what makes a threshold edit that quadruples the universe visible; otherwise
the only symptom is scan passes quietly failing to finish inside the 5-minute cadence.

## Downgrade

Structurally reversible, but **data is lost in both directions of the trade**:

- `bytes_used` is dropped, discarding accumulated bandwidth history. Re-upgrading starts
  the counter at 0 rather than reconstructing it — there is no source to recover it from,
  since FMP does not report historical usage per key.
- `universe_runs` is dropped with its rows, discarding the trailing sizes that
  size-change detection compares against. After a downgrade/upgrade cycle the first few
  builds cannot warn on a material move, because there is no median to move away from.
  They will not warn spuriously either; the detector treats an empty history as "no
  baseline yet".

Neither loss corrupts anything the scanner depends on to produce alerts, which is why the
downgrade is allowed to be lossy rather than refusing to run.
"""
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from app.core.rls import disable_rls, enable_rls

# revision identifiers, used by Alembic.
revision: str = 'b008d4bf3a18'
down_revision: Union[str, Sequence[str], None] = '9c3b774f629a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'universe_runs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('started_at', sa.DateTime(), nullable=False),
        sa.Column('finished_at', sa.DateTime(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('screener_count', sa.Integer(), nullable=True),
        sa.Column('float_rows', sa.Integer(), nullable=True),
        sa.Column('universe_size', sa.Integer(), nullable=True),
        sa.Column('stage1_eligible', sa.Integer(), nullable=True),
        sa.Column('activated', sa.Integer(), nullable=True),
        sa.Column('deactivated', sa.Integer(), nullable=True),
        sa.Column('calls_used', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('bytes_used', sa.BigInteger(), nullable=False, server_default='0'),
        sa.Column('warning', sa.Text(), nullable=True),
        sa.Column('error', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_universe_runs_id'), 'universe_runs', ['id'], unique=False)
    op.create_index(
        op.f('ix_universe_runs_started_at'), 'universe_runs', ['started_at'], unique=False
    )
    # Deny-all for the Supabase Data API. Without this the build history is world-writable
    # through the anon key; tests/integration/test_rls.py fails CI if it is missing.
    enable_rls('universe_runs')

    # server_default makes this safe against a populated api_budget: existing rows get 0
    # rather than violating NOT NULL.
    op.add_column(
        'api_budget',
        sa.Column('bytes_used', sa.BigInteger(), server_default='0', nullable=False),
    )


def downgrade() -> None:
    """Downgrade schema. Lossy — see the module docstring."""
    op.drop_column('api_budget', 'bytes_used')
    disable_rls('universe_runs')
    op.drop_index(op.f('ix_universe_runs_started_at'), table_name='universe_runs')
    op.drop_index(op.f('ix_universe_runs_id'), table_name='universe_runs')
    op.drop_table('universe_runs')
