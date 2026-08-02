"""${message}

Revision ID: ${up_revision}
Revises: ${down_revision | comma,n}
Create Date: ${create_date}

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
${imports if imports else ""}

# revision identifiers, used by Alembic.
revision: str = ${repr(up_revision)}
down_revision: Union[str, Sequence[str], None] = ${repr(down_revision)}
branch_labels: Union[str, Sequence[str], None] = ${repr(branch_labels)}
depends_on: Union[str, Sequence[str], None] = ${repr(depends_on)}


# --------------------------------------------------------------------------------
# CREATING A TABLE? ENABLE ROW-LEVEL SECURITY.
#
#     from app.core.rls import enable_rls
#     ...
#     op.create_table("my_table", ...)
#     enable_rls("my_table")
#
# Tables in `public` without RLS are readable AND writable by anyone holding the
# Supabase anon key, straight through the auto-generated Data API — bypassing this
# backend entirely. tests/integration/test_rls.py fails CI if you forget.
# Background and the deny-all rationale: app/core/rls.py
#
# DROPPING COLUMNS OR TABLES? The downgrade has to work on a POPULATED database.
# Re-adding a NOT NULL column needs a backfill or a server_default; see the
# docstrings in 0ca0181ab014 and c653a931ecaf, and the round-trip tests in
# tests/integration/test_migration_round_trip.py.
# --------------------------------------------------------------------------------


def upgrade() -> None:
    """Upgrade schema."""
    ${upgrades if upgrades else "pass"}


def downgrade() -> None:
    """Downgrade schema."""
    ${downgrades if downgrades else "pass"}
