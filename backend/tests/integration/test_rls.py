"""Row-Level Security enforcement.

**This is a security test, not a schema test.** A `public` table without RLS is readable
and writable by anyone holding the Supabase anon key — which is public by design —
straight through the auto-generated Data API, bypassing this backend entirely. Supabase
flagged this project as CRITICAL for exactly that.

The tables were fixed by hand in production once. A hand-fix does not survive the next
migration, and `docs/PLAN.md` carrying a reminder only works if a human reads the plan at
the right moment. This file converts "remember to enable RLS" into "CI fails if you
didn't", the same way the round-trip test converted "remember to test downgrades".

It runs against a real migrated Postgres, because `relrowsecurity` is a server-side
catalog fact that SQLite cannot model. In CI it FAILS rather than skips when Postgres is
unavailable: a silently skipped security test is worse than no test, because it reads as
a pass.
"""

import os
import uuid

import asyncpg
import pytest

from app.config import get_settings
from app.core.rls import (
    ALL_PUBLIC_TABLES_QUERY,
    RLS_EXEMPT_TABLES,
    enable_rls_sql,
)
from tests.integration.test_migration_round_trip import (
    RLS,
    _asyncpg_dsn,
    _postgres_available,
    _redact,
    _run_alembic,
    _sqlalchemy_url,
)

pytestmark = pytest.mark.timeout(180)


@pytest.fixture
async def migrated_db():
    """A scratch database migrated to head.

    Its own database rather than the developer's working one, so the test reflects what
    `alembic upgrade head` produces on a fresh deploy — which is the thing that has to be
    secure.
    """
    base_url = get_settings().database_url
    admin_dsn = _asyncpg_dsn(base_url, "postgres")

    if not await _postgres_available(admin_dsn):
        message = (
            f"No Postgres reachable at {_redact(admin_dsn)}. "
            f"Start it with `docker compose -f docker-compose.dev.yml up -d`."
        )
        if os.environ.get("CI"):
            pytest.fail(f"The RLS enforcement test cannot be skipped in CI. {message}")
        pytest.skip(message)

    name = f"rls_{uuid.uuid4().hex[:10]}"
    admin = await asyncpg.connect(admin_dsn)
    await admin.execute(f'CREATE DATABASE "{name}"')
    await admin.close()

    url = _sqlalchemy_url(base_url, name)
    _run_alembic("upgrade", "head", database_url=url)

    try:
        yield {"name": name, "sqlalchemy_url": url, "dsn": _asyncpg_dsn(base_url, name)}
    finally:
        admin = await asyncpg.connect(admin_dsn)
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await admin.close()


async def _public_tables(dsn: str) -> dict[str, bool]:
    """Every base table in `public`, mapped to whether RLS is enabled."""
    conn = await asyncpg.connect(dsn)
    try:
        rows = await conn.fetch(str(ALL_PUBLIC_TABLES_QUERY))
        return {r["relname"]: r["relrowsecurity"] for r in rows}
    finally:
        await conn.close()


# ------------------------------------------------------------------ the enforcement


async def test_every_public_table_has_rls(migrated_db):
    """THE test. Every base table in `public` must have RLS enabled after `upgrade head`.

    If this fails, the named tables are exposed through Supabase's Data API to anyone
    with the anon key. Fix them, do not exempt them, unless you can articulate why that
    specific table is safe to publish.
    """
    tables = await _public_tables(migrated_db["dsn"])
    assert tables, "No tables found in `public` — the migration did not run."

    missing = sorted(
        name for name, has_rls in tables.items()
        if not has_rls and name not in RLS_EXEMPT_TABLES
    )

    if missing:
        fix_sql = "\n  ".join(enable_rls_sql(name) for name in missing)
        pytest.fail(
            f"\n"
            f"ROW-LEVEL SECURITY MISSING on {len(missing)} table(s): {', '.join(missing)}\n"
            f"\n"
            f"On Supabase these are readable AND writable by anyone holding the anon key,\n"
            f"through the auto-generated Data API, bypassing the FastAPI backend entirely.\n"
            f"\n"
            f"Fix it in the migration that creates the table:\n"
            f"\n"
            f"    from app.core.rls import enable_rls\n"
            f"    ...\n"
            f"    op.create_table({missing[0]!r}, ...)\n"
            f"    enable_rls({missing[0]!r})\n"
            f"\n"
            f"Equivalent SQL:\n"
            f"\n"
            f"  {fix_sql}\n"
            f"\n"
            f"Do NOT create policies — zero policies is the intended deny-all posture, and\n"
            f"the backend is unaffected because it connects as the table owner. If a table\n"
            f"genuinely belongs on the public internet, add it to RLS_EXEMPT_TABLES in\n"
            f"app/core/rls.py WITH a comment explaining why.\n"
        )


async def test_alembic_version_is_protected_too(migrated_db):
    """Alembic's bookkeeping table is in scope, not exempted.

    It lives in `public`, so the Data API exposes it. Its contents are dull, but a
    writable migration-history table is a real hazard: delete that row and Alembic
    believes the database is unmigrated.
    """
    tables = await _public_tables(migrated_db["dsn"])

    assert "alembic_version" in tables
    assert tables["alembic_version"] is True


async def test_no_table_uses_force_row_level_security(migrated_db):
    """FORCE RLS subjects the table OWNER to RLS as well.

    Since the backend connects as the owner and there are no policies, forcing it would
    deny the application its own tables — turning a security measure into an outage.
    """
    conn = await asyncpg.connect(migrated_db["dsn"])
    try:
        forced = await conn.fetch(
            "SELECT c.relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'public' AND c.relkind = 'r' AND c.relforcerowsecurity"
        )
    finally:
        await conn.close()

    assert [r["relname"] for r in forced] == []


async def test_no_policies_exist(migrated_db):
    """Zero policies is deliberate. A permissive policy added to "make something work"
    would re-open the Data API path this closes."""
    conn = await asyncpg.connect(migrated_db["dsn"])
    try:
        policies = await conn.fetch(
            "SELECT tablename, policyname FROM pg_policies WHERE schemaname = 'public'"
        )
    finally:
        await conn.close()

    assert policies == [], (
        f"Unexpected RLS policies: {[(p['tablename'], p['policyname']) for p in policies]}. "
        f"This project denies the Data API entirely; the backend bypasses RLS as table owner."
    )


# ------------------------------------------------------------------ the exemption list


def test_every_exemption_is_deliberate():
    """The allowlist is empty today. If it grows, this test is the reminder that each
    entry is a decision to publish a table, not a convenience."""
    assert isinstance(RLS_EXEMPT_TABLES, frozenset)
    assert RLS_EXEMPT_TABLES == frozenset(), (
        f"RLS_EXEMPT_TABLES is no longer empty: {sorted(RLS_EXEMPT_TABLES)}. "
        f"That is allowed, but each entry must carry a comment in app/core/rls.py "
        f"explaining why the table is safe to expose through the Supabase Data API. "
        f"Update this test deliberately once you have done so."
    )


# ------------------------------------------------------------------ the migration


async def test_the_rls_migration_is_idempotent(migrated_db):
    """Production was fixed by hand before this migration existed, so re-applying it
    there must be a no-op rather than an error."""
    url, dsn = migrated_db["sqlalchemy_url"], migrated_db["dsn"]

    # Pinned to the RLS revision: "-1" from head retargets whenever a new migration
    # lands on top, which has already caused false failures elsewhere in this suite.
    _run_alembic("downgrade", f"{RLS}-1", database_url=url)
    after_downgrade = await _public_tables(dsn)
    assert not any(after_downgrade.values()), "Downgrade should have disabled RLS"

    _run_alembic("upgrade", "head", database_url=url)
    after_upgrade = await _public_tables(dsn)
    assert all(
        has_rls for name, has_rls in after_upgrade.items() if name not in RLS_EXEMPT_TABLES
    )

    # And applying it to an already-enabled database changes nothing.
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("ALTER TABLE public.alerts ENABLE ROW LEVEL SECURITY")
    finally:
        await conn.close()
    assert (await _public_tables(dsn))["alerts"] is True
