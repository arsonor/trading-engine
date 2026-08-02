"""Row-Level Security helpers and the single source of truth for the RLS policy.

## Why this exists

Supabase exposes an auto-generated Data API over the `public` schema. Anyone holding the
project URL and the anon key — which is public by design — can read, edit and delete any
table there **unless RLS is enabled**, bypassing the FastAPI backend entirely. Supabase
flagged this project as CRITICAL for exactly that reason.

The tables were fixed by hand in production once. That fix is not durable: every table a
future migration creates arrives without RLS, and V2/V3 add several. This module plus
`tests/integration/test_rls.py` turn "remember to enable RLS" into "CI fails if you
didn't".

## Why RLS with NO policies is the correct configuration

This project never uses the Supabase Data API. The backend connects directly over
Postgres as the table owner, which carries BYPASSRLS. So RLS with zero policies denies
the Data API's `anon` and `authenticated` roles while leaving the application completely
unaffected. Do not add permissive policies to "make things work" — nothing is supposed to
work through that path.

`FORCE ROW LEVEL SECURITY` is deliberately NOT used. That subjects the table owner to RLS
too, which would break the application's own access.

## The assumption this rests on

**The application's database role owns its tables, or has BYPASSRLS.** That is true today
(the backend connects as `postgres`, which is the owner and a superuser). If a future
deployment connects as a restricted role, RLS stops being a no-op for the application and
becomes load-bearing: every query would be denied until policies are written. Anyone
changing the connection role needs to know that before, not after.
"""

from sqlalchemy import text

# Tables deliberately excluded from the RLS requirement.
#
# EMPTY BY DESIGN. `alembic_version` is included in the requirement rather than exempted:
# it lives in `public`, so the Data API exposes it, and while its contents are dull, a
# writable migration-history table is a real hazard — deleting that row makes Alembic
# believe the database is unmigrated. Enabling RLS on it costs nothing, since Alembic
# connects as the owner.
#
# Anything added here is a visible, reviewable decision. Each entry must carry a comment
# explaining why the table is safe to expose.
RLS_EXEMPT_TABLES: frozenset[str] = frozenset()

# Postgres accepts these on a table that is already in the target state, so migrations
# using them stay idempotent — important because production was already fixed by hand.
_ENABLE_SQL = 'ALTER TABLE public."{table}" ENABLE ROW LEVEL SECURITY'
_DISABLE_SQL = 'ALTER TABLE public."{table}" DISABLE ROW LEVEL SECURITY'

# Every base table in `public` that does not have RLS on.
MISSING_RLS_QUERY = text(
    """
    SELECT c.relname
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind = 'r'
      AND NOT c.relrowsecurity
    ORDER BY c.relname
    """
)

ALL_PUBLIC_TABLES_QUERY = text(
    """
    SELECT c.relname, c.relrowsecurity
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind = 'r'
    ORDER BY c.relname
    """
)


def enable_rls(table: str) -> None:
    """Enable RLS on `table` from inside an Alembic migration.

    Idempotent: safe on a table that already has it, which is why this migration can be
    re-applied to the hand-fixed production database.

    Usage in a migration::

        from app.core.rls import enable_rls

        def upgrade() -> None:
            op.create_table("my_new_table", ...)
            enable_rls("my_new_table")
    """
    # Imported lazily: this module is also used by the enforcement test and by app code,
    # neither of which should require Alembic's migration context to exist.
    from alembic import op

    op.execute(_ENABLE_SQL.format(table=table))


def disable_rls(table: str) -> None:
    """Disable RLS on `table` — for migration downgrades only.

    A downgrade that leaves RLS on would be a schema mismatch, but note that running it
    against Supabase re-opens the table to the Data API. Say so in the downgrade
    docstring of any migration that calls this.
    """
    from alembic import op

    op.execute(_DISABLE_SQL.format(table=table))


def enable_rls_sql(table: str) -> str:
    """The raw statement, for callers outside a migration context (e.g. error messages)."""
    return _ENABLE_SQL.format(table=table) + ";"
