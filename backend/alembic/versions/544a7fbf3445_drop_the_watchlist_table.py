"""Drop the watchlist table

Revision ID: 544a7fbf3445
Revises: c653a931ecaf
Create Date: 2026-08-02 18:04:52.140464

"""

import logging
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = '544a7fbf3445'
down_revision: Union[str, Sequence[str], None] = 'c653a931ecaf'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")


def upgrade() -> None:
    """Drop `watchlist`.

    The watchlist is a v1 concept: a curated list of symbols to stream quotes for. The
    v2 scanner's premise is the opposite — filter the whole universe every morning — so
    a favourites list has no role in producing alerts. It survived Phase 3.5 only
    because nothing in that phase's scope asked about it.

    By now it had no UI (the watchlist-era pages went in Phase 3), no mention in the v2
    specification, and no reader outside its own CRUD endpoints. Every schema change had
    to consider it regardless. Same reasoning as the MCP removal: git keeps the code if a
    favourites feature ever earns a place on the roadmap, and until then it is a standing
    tax on everything else.

    ## Data

    Dropping the table deletes its rows. They are user-entered symbols with optional
    notes, nothing derived and nothing the scanner reads. The count is logged first so a
    deploy record shows what was removed. The downgrade recreates the table **empty** —
    see its docstring.
    """
    bind = op.get_bind()

    # to_regclass avoids an error if the table is already absent, so this migration is
    # safe to run against a database where it was removed by hand.
    exists = bind.execute(
        sa.text("SELECT to_regclass('public.watchlist') IS NOT NULL")
    ).scalar_one()
    if not exists:
        logger.info("`watchlist` is already absent; nothing to drop.")
        return

    rows = bind.execute(sa.text("SELECT count(*) FROM watchlist")).scalar_one()
    logger.info("Dropping `watchlist` with %s row(s). Rows are not recoverable by a "
                "downgrade; see the migration docstring.", rows)

    op.drop_index(op.f('ix_watchlist_symbol'), table_name='watchlist')
    op.drop_index(op.f('ix_watchlist_id'), table_name='watchlist')
    op.drop_table('watchlist')


def downgrade() -> None:
    """Recreate `watchlist`, empty.

    The schema is restored exactly as the initial migration created it, including the
    unique index on `symbol`. **The rows are not restored** — they were deleted with the
    table and a downgrade has no record of them. Take a backup before downgrading a
    database whose watchlist you care about.

    Note that the application no longer has a Watchlist model, API or UI, so a
    downgraded database will simply carry an unused table until the revision is
    re-applied.
    """
    op.create_table(
        'watchlist',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('symbol', sa.String(length=10), nullable=False),
        sa.Column('added_at', sa.DateTime(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_watchlist_id'), 'watchlist', ['id'], unique=False)
    op.create_index(op.f('ix_watchlist_symbol'), 'watchlist', ['symbol'], unique=True)
