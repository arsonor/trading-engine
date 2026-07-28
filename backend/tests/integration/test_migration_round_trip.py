"""Migration round-trip tests against a real Postgres.

**Why this file exists.** The v2 alert migration's downgrade restored
`entry_price NOT NULL` and `setup_type NOT NULL`, which scanner alerts legitimately
leave empty. It round-tripped perfectly on an empty database and failed on every
populated one — so production had no rollback path at all, and nothing caught it.

The lesson generalises: **a migration test without data proves almost nothing.** Every
test here seeds realistic rows before touching the downgrade, and the seed deliberately
includes the awkward shapes — scanner rows with no `entry_price`, no `setup_type`, and a
breakout row with a null `upside_pct`.

These tests run the real `alembic` CLI in a subprocess against a scratch database, so
they exercise the same code path as `alembic upgrade head` on Render, including
`env.py`'s connection configuration and advisory lock. They are skipped when no Postgres
is reachable, so a machine without Docker can still run the rest of the suite.
"""

import os
import subprocess
import sys
import uuid
from pathlib import Path

import asyncpg
import pytest

from app.config import get_settings

BACKEND_DIR = Path(__file__).parents[2]

HEAD = "0ca0181ab014"
PREVIOUS = "5c3b382f1d74"

pytestmark = pytest.mark.timeout(180)


# --------------------------------------------------------------------------- helpers


def _asyncpg_dsn(sqlalchemy_url: str, database: str | None = None) -> str:
    """Convert a SQLAlchemy DSN to one asyncpg.connect understands."""
    dsn = sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://")
    if database is not None:
        base, _, _ = dsn.rpartition("/")
        dsn = f"{base}/{database}"
    return dsn


def _sqlalchemy_url(base_url: str, database: str) -> str:
    base, _, _ = base_url.rpartition("/")
    return f"{base}/{database}"


def _redact(dsn: str) -> str:
    """Host/port/db only — these strings end up in CI logs."""
    if "@" in dsn:
        return dsn.split("@", 1)[1]
    return dsn.rsplit("/", 1)[-1]


async def _postgres_available(admin_dsn: str) -> bool:
    try:
        conn = await asyncpg.connect(admin_dsn, timeout=5)
    except Exception:
        return False
    await conn.close()
    return True


def _run_alembic(*args: str, database_url: str, expect_success: bool = True):
    """Invoke the real alembic CLI against `database_url`."""
    env = {
        **os.environ,
        # Both are set: env.py reads MIGRATION_DATABASE_URL, and app.config still
        # validates DATABASE_URL on import. Env vars outrank the .env file.
        "DATABASE_URL": database_url,
        "MIGRATION_DATABASE_URL": database_url,
        "DEBUG": "false",
    }
    result = subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=BACKEND_DIR,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    if expect_success and result.returncode != 0:
        raise AssertionError(
            f"alembic {' '.join(args)} failed ({result.returncode})\n"
            f"--- stdout ---\n{result.stdout}\n--- stderr ---\n{result.stderr}"
        )
    return result


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
async def scratch_db():
    """A throwaway Postgres database, dropped afterwards.

    Never touches the developer's working database, and never Supabase.
    """
    base_url = get_settings().database_url
    admin_dsn = _asyncpg_dsn(base_url, "postgres")

    if not await _postgres_available(admin_dsn):
        message = (
            f"No Postgres reachable at {_redact(admin_dsn)}. "
            f"Start it with `docker compose -f docker-compose.dev.yml up -d`."
        )
        if os.environ.get("CI"):
            # Skipping in CI would leave the migration path unverified while the build
            # went green — precisely the hole that let the broken downgrade ship.
            pytest.fail(f"Migration round-trip tests cannot be skipped in CI. {message}")
        pytest.skip(message)

    name = f"roundtrip_{uuid.uuid4().hex[:10]}"
    admin = await asyncpg.connect(admin_dsn)
    await admin.execute(f'CREATE DATABASE "{name}"')
    await admin.close()

    try:
        yield {
            "name": name,
            "sqlalchemy_url": _sqlalchemy_url(base_url, name),
            "dsn": _asyncpg_dsn(base_url, name),
        }
    finally:
        admin = await asyncpg.connect(admin_dsn)
        # Terminate stragglers so DROP cannot block on a lingering connection.
        await admin.execute(
            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
            "WHERE datname = $1 AND pid <> pg_backend_pid()",
            name,
        )
        await admin.execute(f'DROP DATABASE IF EXISTS "{name}"')
        await admin.close()


async def _seed_realistic_data(dsn: str) -> dict:
    """Seed the shapes that actually exist in production.

    The scanner rows are the point: no `entry_price`, no `setup_type`, and one with a
    null `upside_pct` (a ticker trading above every resistance level).
    """
    conn = await asyncpg.connect(dsn)
    try:
        rule_id = await conn.fetchval(
            "INSERT INTO rules (name, rule_type, config_yaml, is_active, priority, "
            "created_at, updated_at) "
            "VALUES ('legacy rule', 'price', 'conditions: []', true, 1, now(), now()) "
            "RETURNING id"
        )
        scan_run_id = await conn.fetchval(
            "INSERT INTO scan_runs (started_at, finished_at, status, profile, "
            "api_calls_used) "
            "VALUES (now(), now(), 'completed', 'demo', 0) RETURNING id"
        )

        # --- legacy v1 rule-engine alerts: both required columns populated ---
        for symbol, setup, price in [("AAPL", "breakout", 150.5), ("TSLA", "momentum", 250.0)]:
            await conn.execute(
                "INSERT INTO alerts (rule_id, symbol, timestamp, setup_type, entry_price, "
                "confidence_score, is_read, created_at, updated_at) "
                "VALUES ($1, $2, now(), $3, $4, 0.8, false, now(), now())",
                rule_id,
                symbol,
                setup,
                price,
            )

        # --- v2 scanner alerts: NULL entry_price and NULL setup_type ---
        scanner_rows = [
            ("ADBE", 240.87, 15.75, 278.81, "sma_200"),
            ("BA", 220.0, 7.95, 237.48, "high_20d"),
            # The breakout case: above every resistance level, so upside is unmeasured.
            ("BRKO", 349.67, None, None, None),
        ]
        for symbol, ref_price, upside, resistance, source in scanner_rows:
            await conn.execute(
                "INSERT INTO alerts (symbol, timestamp, session_date, scan_timestamp, "
                "scan_run_id, profile, gap_pct, rvol_pct, rvol_mode, rvol_is_approximate, "
                "entry_reference_price, nearest_resistance, resistance_source, upside_pct, "
                "suggested_entry_window, confidence_score, is_final_pass, is_read, "
                "created_at, updated_at) "
                "VALUES ($1, now(), DATE '2026-07-28', now(), $2, 'demo', 7.0, 25.0, "
                "'simple', true, $3, $4, $5, $6, '09:30-10:00 ET', 0.6, true, false, "
                "now(), now())",
                symbol,
                scan_run_id,
                ref_price,
                resistance,
                source,
                upside,
            )

        await conn.execute(
            "INSERT INTO scanner_settings (id, profile, updated_at) VALUES (1, 'demo', now())"
        )

        return {
            "rule_id": rule_id,
            "scan_run_id": scan_run_id,
            "total_alerts": 5,
            "scanner_symbols": ["ADBE", "BA", "BRKO"],
            "scanner_ref_prices": {"ADBE": 240.87, "BA": 220.0, "BRKO": 349.67},
        }
    finally:
        await conn.close()


async def _column_is_nullable(dsn: str, table: str, column: str) -> bool:
    conn = await asyncpg.connect(dsn)
    try:
        value = await conn.fetchval(
            "SELECT is_nullable FROM information_schema.columns "
            "WHERE table_name = $1 AND column_name = $2",
            table,
            column,
        )
        return value == "YES"
    finally:
        await conn.close()


async def _table_exists(dsn: str, table: str) -> bool:
    conn = await asyncpg.connect(dsn)
    try:
        return bool(
            await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{table}")
        )
    finally:
        await conn.close()


# --------------------------------------------------------------------------- tests


async def test_round_trip_preserves_data_with_scanner_alerts_present(scratch_db):
    """THE regression test: upgrade, seed real v2 data, downgrade, upgrade back.

    Before the fix this failed at the downgrade with
    `NotNullViolationError: column "entry_price" of relation "alerts" contains null
    values` — but only because data was present. On an empty database it passed.
    """
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", "head", database_url=url)
    seeded = await _seed_realistic_data(dsn)

    # --- downgrade one step, the step that used to fail ---
    _run_alembic("downgrade", "-1", database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM alerts") == seeded["total_alerts"]
        # No row lost, and both v1-required columns satisfied for every row.
        assert await conn.fetchval("SELECT count(*) FROM alerts WHERE entry_price IS NULL") == 0
        assert await conn.fetchval("SELECT count(*) FROM alerts WHERE setup_type IS NULL") == 0

        # entry_price came from entry_reference_price, value-for-value.
        for symbol, expected in seeded["scanner_ref_prices"].items():
            actual = await conn.fetchval(
                "SELECT entry_price FROM alerts WHERE symbol = $1", symbol
            )
            assert actual == pytest.approx(expected), symbol

        # Scanner rows got the v1 vocabulary...
        scanner_setups = await conn.fetch(
            "SELECT symbol, setup_type FROM alerts WHERE symbol = ANY($1::text[])",
            seeded["scanner_symbols"],
        )
        assert {r["setup_type"] for r in scanner_setups} == {"gap_up"}

        # ...and legacy rows were left exactly as they were.
        assert (
            await conn.fetchval("SELECT setup_type FROM alerts WHERE symbol = 'AAPL'")
            == "breakout"
        )
        assert await conn.fetchval(
            "SELECT entry_price FROM alerts WHERE symbol = 'AAPL'"
        ) == pytest.approx(150.5)
    finally:
        await conn.close()

    # The v1 schema really is restored, not merely tolerated.
    assert not await _column_is_nullable(dsn, "alerts", "entry_price")
    assert not await _column_is_nullable(dsn, "alerts", "setup_type")
    assert not await _table_exists(dsn, "scanner_settings")

    # --- and back up again ---
    _run_alembic("upgrade", "head", database_url=url)

    assert await _column_is_nullable(dsn, "alerts", "entry_price")
    assert await _column_is_nullable(dsn, "alerts", "setup_type")
    assert await _table_exists(dsn, "scanner_settings")

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM alerts") == seeded["total_alerts"]
        # v2 columns are back, and empty — the documented, irreversible loss.
        assert await conn.fetchval("SELECT count(*) FROM alerts WHERE gap_pct IS NOT NULL") == 0
    finally:
        await conn.close()


async def test_downgrade_aborts_loudly_when_a_row_cannot_be_converted(scratch_db):
    """A row with neither an entry price nor a scanner origin cannot be represented in
    v1. That must stop the downgrade with an actionable message, not a bare
    NotNullViolationError, and must change nothing."""
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", "head", database_url=url)
    await _seed_realistic_data(dsn)

    conn = await asyncpg.connect(dsn)
    try:
        # No entry_price, no entry_reference_price, no session_date: unbackfillable.
        await conn.execute(
            "INSERT INTO alerts (symbol, timestamp, is_read, created_at, updated_at) "
            "VALUES ('ORPHAN', now(), false, now(), now())"
        )
    finally:
        await conn.close()

    result = _run_alembic("downgrade", "-1", database_url=url, expect_success=False)

    assert result.returncode != 0
    combined = result.stdout + result.stderr
    assert "cannot be represented in the v1 schema" in combined
    assert "ORPHAN" in combined
    assert "rolled back" in combined

    # Nothing changed: still at head, still 6 rows, v2 columns intact.
    current = _run_alembic("current", database_url=url)
    assert HEAD in current.stdout

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM alerts") == 6
        assert await conn.fetchval("SELECT count(*) FROM alerts WHERE gap_pct IS NOT NULL") == 3
    finally:
        await conn.close()

    assert await _column_is_nullable(dsn, "alerts", "entry_price")


async def test_full_chain_down_to_base_and_back_up(scratch_db):
    """Every migration's downgrade, run in order against a populated database.

    This is what catches the same defect class in migrations other than the one that
    prompted the fix.
    """
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", "head", database_url=url)
    await _seed_realistic_data(dsn)

    _run_alembic("downgrade", "base", database_url=url)

    # base means no application tables at all.
    for table in ("alerts", "rules", "watchlist", "universe", "scan_runs", "scanner_settings"):
        assert not await _table_exists(dsn, table), table

    _run_alembic("upgrade", "head", database_url=url)

    for table in ("alerts", "rules", "watchlist", "universe", "scan_runs", "scanner_settings"):
        assert await _table_exists(dsn, table), table

    conn = await asyncpg.connect(dsn)
    try:
        # Down-to-base drops the tables, so the rows are gone. Asserted explicitly so
        # nobody mistakes this for data preservation.
        assert await conn.fetchval("SELECT count(*) FROM alerts") == 0
    finally:
        await conn.close()


async def test_stepwise_downgrade_of_the_scanner_tables_migration(scratch_db):
    """The 5c3b382f1d74 downgrade drops tables that `alerts` referenced via
    `scan_run_id`. Ordering only works because the later revision drops that FK and
    column first; this pins that the two downgrades compose."""
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", "head", database_url=url)
    await _seed_realistic_data(dsn)

    _run_alembic("downgrade", "-1", database_url=url)  # head -> 5c3b382f1d74
    _run_alembic("downgrade", "-1", database_url=url)  # -> f5e101dcbc55

    assert not await _table_exists(dsn, "scan_runs")
    assert await _table_exists(dsn, "alerts")

    conn = await asyncpg.connect(dsn)
    try:
        # The v1 alerts survive the scanner-table teardown.
        assert await conn.fetchval("SELECT count(*) FROM alerts") == 5
        assert await conn.fetchval(
            "SELECT count(*) FROM information_schema.columns "
            "WHERE table_name = 'alerts' AND column_name = 'scan_run_id'"
        ) == 0
    finally:
        await conn.close()

    _run_alembic("upgrade", "head", database_url=url)
    assert await _table_exists(dsn, "scan_runs")
