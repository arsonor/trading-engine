"""Enable Row-Level Security on all public tables

Revision ID: dbdf5784db31
Revises: 544a7fbf3445
Create Date: 2026-08-02 18:21:47.922573

"""

import logging
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from app.core.rls import disable_rls, enable_rls

# revision identifiers, used by Alembic.
revision: str = 'dbdf5784db31'
down_revision: Union[str, Sequence[str], None] = '544a7fbf3445'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

logger = logging.getLogger("alembic.runtime.migration")

# Every base table in `public` at this revision.
#
# Listed explicitly rather than enumerated from the catalog so the change is reviewable
# in the diff. A table missed here is caught by tests/integration/test_rls.py, which is
# the actual guarantee — this list is the fix, that test is the enforcement.
TABLES = (
    "alerts",
    "api_budget",
    "premarket_volume_profile",
    "reference_data",
    "scan_runs",
    "scanner_settings",
    "universe",
    # Alembic's own bookkeeping table. In scope deliberately: it lives in `public`, so
    # Supabase's Data API exposes it, and a writable migration-history table is a real
    # hazard — deleting its row makes Alembic believe the database is unmigrated.
    # Alembic connects as the owner, which carries BYPASSRLS, so this does not affect it.
    "alembic_version",
)


def upgrade() -> None:
    """Enable RLS on every table in `public`.

    ## What this protects against

    Supabase auto-generates a Data API over the `public` schema. Without RLS, anyone
    holding the project URL and the anon key — public by design — can read, edit and
    delete these tables directly, bypassing the FastAPI backend. Supabase flagged this
    project as CRITICAL for that reason.

    ## Why no policies are created

    Zero policies is the intended deny-all posture. This project never uses the Data API;
    the backend connects directly over Postgres as the table owner, which carries
    BYPASSRLS. RLS with no policies therefore denies `anon`/`authenticated` while leaving
    the application untouched. `FORCE ROW LEVEL SECURITY` is deliberately not used — it
    would subject the owner to RLS too and break the application's own access.

    See `app/core/rls.py` for the assumption this rests on (owner or BYPASSRLS), which
    becomes load-bearing if a future deployment connects as a restricted role.

    ## Idempotency

    `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` is a no-op on a table that already has
    it, and each table is guarded by `to_regclass`. Production was already fixed by hand,
    so this migration must be safe to apply there — it is.
    """
    bind = op.get_bind()
    enabled, skipped = [], []

    for table in TABLES:
        exists = bind.execute(
            sa.text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"public.{table}"},
        ).scalar_one()
        if not exists:
            skipped.append(table)
            continue
        enable_rls(table)
        enabled.append(table)

    logger.info("RLS enabled on %s table(s): %s", len(enabled), ", ".join(enabled))
    if skipped:
        logger.info("Skipped %s absent table(s): %s", len(skipped), ", ".join(skipped))


def downgrade() -> None:
    """Disable RLS on every table.

    **This re-opens every table to Supabase's Data API**, which is the CRITICAL issue the
    upgrade exists to close. It is here because a downgrade must restore the previous
    schema state, not because running it is ever a good idea on a Supabase-hosted
    database. If you downgrade past this revision in production, re-enable RLS by hand
    immediately.
    """
    bind = op.get_bind()

    for table in TABLES:
        exists = bind.execute(
            sa.text("SELECT to_regclass(:qualified) IS NOT NULL"),
            {"qualified": f"public.{table}"},
        ).scalar_one()
        if exists:
            disable_rls(table)

    logger.warning(
        "RLS DISABLED on all public tables. On Supabase these are now readable and "
        "writable through the Data API by anyone holding the anon key."
    )
