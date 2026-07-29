"""Migration round-trip tests against a real Postgres.

**Why this file exists.** The v2 alert migration's downgrade restored
`entry_price NOT NULL` and `setup_type NOT NULL`, which scanner alerts legitimately
leave empty. It round-tripped perfectly on an empty database and failed on every
populated one — so production had no rollback path at all, and nothing caught it.

The lesson generalises: **a migration test without data proves almost nothing.** Every
test here seeds realistic rows before touching a migration, and the seeds deliberately
include the awkward shapes — scanner rows with no `entry_price` or `setup_type`, a
breakout row with a null `upside_pct`, and (for Phase 3.5) both v1-origin and v2-origin
alerts in the same table.

These tests run the real `alembic` CLI in a subprocess against a scratch database, so
they exercise the same code path as `alembic upgrade head` on Render, including
`env.py`'s connection configuration and advisory lock. They are skipped when no Postgres
is reachable — except in CI, where they fail instead.
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

# Revisions this file navigates between.
SCANNER_TABLES = "5c3b382f1d74"  # universe, reference_data, scan_runs, api_budget
V2_CONTRACT = "0ca0181ab014"  # v2 alert columns added; v1 columns still present
HEAD = "c653a931ecaf"  # Phase 3.5: v1 columns dropped, symbol -> ticker, rules dropped

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


# --------------------------------------------------------------------------- seeding


async def _seed_at_v2_contract(dsn: str) -> dict:
    """Seed the `0ca0181ab014` schema, where v1 and v2 columns coexist.

    This is the shape a real database had before Phase 3.5: legacy rule-engine rows
    (`session_date IS NULL`, v1 columns populated) alongside scanner rows
    (`session_date` set, v1 columns null).
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

        # --- v1-origin rows: rule engine, no session_date ---
        for symbol, setup, price in [("AAPL", "breakout", 150.5), ("TSLA", "momentum", 250.0)]:
            await conn.execute(
                "INSERT INTO alerts (rule_id, symbol, timestamp, setup_type, entry_price, "
                "stop_loss, target_price, market_data_json, confidence_score, is_read, "
                "created_at, updated_at) "
                "VALUES ($1, $2, now(), $3, $4, $5, $6, $7, 0.8, false, now(), now())",
                rule_id, symbol, setup, price, price * 0.97, price * 1.06,
                '{"volume": 1000000}',
            )

        # --- v2-origin rows: scanner, session_date set, v1 columns null ---
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
                symbol, scan_run_id, ref_price, resistance, source, upside,
            )

        await conn.execute(
            "INSERT INTO scanner_settings (id, profile, updated_at) VALUES (1, 'demo', now())"
        )

        return {
            "rule_id": rule_id,
            "scan_run_id": scan_run_id,
            "v1_origin": ["AAPL", "TSLA"],
            "v2_origin": ["ADBE", "BA", "BRKO"],
            "total_alerts": 5,
            "scanner_ref_prices": {"ADBE": 240.87, "BA": 220.0, "BRKO": 349.67},
        }
    finally:
        await conn.close()


async def _seed_at_head(dsn: str) -> dict:
    """Seed the head schema, where `alerts` has only v2 columns and uses `ticker`."""
    conn = await asyncpg.connect(dsn)
    try:
        scan_run_id = await conn.fetchval(
            "INSERT INTO scan_runs (started_at, finished_at, status, profile, "
            "api_calls_used) "
            "VALUES (now(), now(), 'completed', 'demo', 0) RETURNING id"
        )
        for ticker, ref_price, upside in [("ADBE", 240.87, 15.75), ("BRKO", 349.67, None)]:
            await conn.execute(
                "INSERT INTO alerts (ticker, timestamp, session_date, scan_timestamp, "
                "scan_run_id, profile, gap_pct, rvol_pct, rvol_is_approximate, "
                "entry_reference_price, upside_pct, confidence_score, is_final_pass, "
                "is_read, created_at, updated_at) "
                "VALUES ($1, now(), DATE '2026-07-28', now(), $2, 'demo', 7.0, 25.0, true, "
                "$3, $4, 0.6, true, false, now(), now())",
                ticker, scan_run_id, ref_price, upside,
            )
        return {"scan_run_id": scan_run_id, "tickers": ["ADBE", "BRKO"]}
    finally:
        await conn.close()


# --------------------------------------------------------------------------- introspection


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


async def _column_exists(dsn: str, table: str, column: str) -> bool:
    conn = await asyncpg.connect(dsn)
    try:
        return bool(
            await conn.fetchval(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = $1 AND column_name = $2",
                table,
                column,
            )
        )
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


async def _index_exists(dsn: str, name: str) -> bool:
    conn = await asyncpg.connect(dsn)
    try:
        return bool(await conn.fetchval("SELECT to_regclass($1) IS NOT NULL", f"public.{name}"))
    finally:
        await conn.close()


# ======================================================================= Phase 3.5


async def test_phase35_upgrade_deletes_v1_rows_and_preserves_v2(scratch_db):
    """The documented data decision, pinned.

    Seeded with BOTH origins. v1-origin rows are deleted (everything that gave them
    meaning is dropped by the same migration); v2-origin rows survive intact under the
    renamed column.
    """
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", V2_CONTRACT, database_url=url)
    seeded = await _seed_at_v2_contract(dsn)

    result = _run_alembic("upgrade", "head", database_url=url)
    # The count is logged so a deploy record shows what was removed.
    assert "Deleting 2 v1-origin alert row(s)" in result.stdout + result.stderr

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM alerts") == len(seeded["v2_origin"])

        tickers = [
            r["ticker"] for r in await conn.fetch("SELECT ticker FROM alerts ORDER BY ticker")
        ]
        assert tickers == sorted(seeded["v2_origin"])

        # v2 payload survived the rename unchanged.
        adbe = await conn.fetchrow("SELECT * FROM alerts WHERE ticker = 'ADBE'")
        assert adbe["gap_pct"] == 7.0
        assert adbe["entry_reference_price"] == pytest.approx(240.87)
        assert adbe["upside_pct"] == pytest.approx(15.75)
        assert adbe["profile"] == "demo"

        # The breakout row keeps its null upside — the deferred-strategy case.
        brko = await conn.fetchrow("SELECT * FROM alerts WHERE ticker = 'BRKO'")
        assert brko["upside_pct"] is None
        assert brko["nearest_resistance"] is None
    finally:
        await conn.close()

    # Schema: v1 columns gone, ticker in place, rules dropped.
    for column in ("symbol", "setup_type", "entry_price", "stop_loss", "target_price",
                   "market_data_json", "rule_id"):
        assert not await _column_exists(dsn, "alerts", column), column
    assert await _column_exists(dsn, "alerts", "ticker")
    assert not await _table_exists(dsn, "rules")
    assert await _index_exists(dsn, "ix_alerts_ticker")
    assert not await _index_exists(dsn, "ix_alerts_symbol")


async def test_phase35_downgrade_restores_the_v1_shape(scratch_db):
    """Downgrade must succeed on a populated database and restore the previous schema."""
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", "head", database_url=url)
    seeded = await _seed_at_head(dsn)

    _run_alembic("downgrade", "-1", database_url=url)

    # Column renamed back, v1 columns restored NULLABLE (v2 rows have no values for them).
    assert await _column_exists(dsn, "alerts", "symbol")
    assert not await _column_exists(dsn, "alerts", "ticker")
    for column in ("setup_type", "entry_price", "stop_loss", "target_price",
                   "market_data_json", "rule_id"):
        assert await _column_exists(dsn, "alerts", column), column
        assert await _column_is_nullable(dsn, "alerts", column), column

    assert await _table_exists(dsn, "rules")
    assert await _index_exists(dsn, "ix_alerts_symbol")

    conn = await asyncpg.connect(dsn)
    try:
        # Rows preserved, carried across the rename.
        symbols = [
            r["symbol"] for r in await conn.fetch("SELECT symbol FROM alerts ORDER BY symbol")
        ]
        assert symbols == sorted(seeded["tickers"])
        # The restored v1 columns are empty — documented, irreversible.
        assert await conn.fetchval(
            "SELECT count(*) FROM alerts WHERE entry_price IS NOT NULL"
        ) == 0
        # `rules` comes back empty.
        assert await conn.fetchval("SELECT count(*) FROM rules") == 0
        # v2 data untouched.
        assert await conn.fetchval(
            "SELECT entry_reference_price FROM alerts WHERE symbol = 'ADBE'"
        ) == pytest.approx(240.87)
    finally:
        await conn.close()

    # ...and back up again.
    _run_alembic("upgrade", "head", database_url=url)
    assert await _column_exists(dsn, "alerts", "ticker")
    assert not await _table_exists(dsn, "rules")

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM alerts") == len(seeded["tickers"])
    finally:
        await conn.close()


async def test_phase35_upgrade_is_a_no_op_when_no_v1_rows_exist(scratch_db):
    """The common case on a database that only ever ran the scanner."""
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", V2_CONTRACT, database_url=url)
    conn = await asyncpg.connect(dsn)
    try:
        run_id = await conn.fetchval(
            "INSERT INTO scan_runs (started_at, status, profile, api_calls_used) "
            "VALUES (now(), 'completed', 'production', 0) RETURNING id"
        )
        await conn.execute(
            "INSERT INTO alerts (symbol, timestamp, session_date, scan_run_id, profile, "
            "gap_pct, rvol_is_approximate, is_final_pass, is_read, created_at, updated_at) "
            "VALUES ('LOWF', now(), DATE '2026-07-28', $1, 'production', 5.0, false, true, "
            "false, now(), now())",
            run_id,
        )
    finally:
        await conn.close()

    result = _run_alembic("upgrade", "head", database_url=url)
    assert "Deleting" not in result.stdout + result.stderr

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval("SELECT ticker FROM alerts") == "LOWF"
    finally:
        await conn.close()


# ======================================================================= v2 contract


async def test_v2_contract_downgrade_backfills_entry_price(scratch_db):
    """The regression test for the earlier hotfix.

    Before that fix this failed with `NotNullViolationError: column "entry_price" of
    relation "alerts" contains null values` — but only because data was present. On an
    empty database it passed.
    """
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", V2_CONTRACT, database_url=url)
    seeded = await _seed_at_v2_contract(dsn)

    _run_alembic("downgrade", "-1", database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM alerts") == seeded["total_alerts"]
        assert await conn.fetchval("SELECT count(*) FROM alerts WHERE entry_price IS NULL") == 0
        assert await conn.fetchval("SELECT count(*) FROM alerts WHERE setup_type IS NULL") == 0

        # entry_price came from entry_reference_price, value-for-value.
        for symbol, expected in seeded["scanner_ref_prices"].items():
            actual = await conn.fetchval(
                "SELECT entry_price FROM alerts WHERE symbol = $1", symbol
            )
            assert actual == pytest.approx(expected), symbol

        # Scanner rows got the v1 vocabulary; legacy rows were left alone.
        scanner_setups = await conn.fetch(
            "SELECT setup_type FROM alerts WHERE symbol = ANY($1::text[])",
            seeded["v2_origin"],
        )
        assert {r["setup_type"] for r in scanner_setups} == {"gap_up"}
        assert (
            await conn.fetchval("SELECT setup_type FROM alerts WHERE symbol = 'AAPL'")
            == "breakout"
        )
    finally:
        await conn.close()

    assert not await _column_is_nullable(dsn, "alerts", "entry_price")
    assert not await _column_is_nullable(dsn, "alerts", "setup_type")

    _run_alembic("upgrade", V2_CONTRACT, database_url=url)
    assert await _column_is_nullable(dsn, "alerts", "entry_price")


async def test_v2_contract_downgrade_aborts_loudly_on_an_unconvertible_row(scratch_db):
    """A row with neither an entry price nor a scanner origin cannot be represented in
    v1. That must stop the downgrade with an actionable message, not a bare
    NotNullViolationError, and must change nothing."""
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", V2_CONTRACT, database_url=url)
    await _seed_at_v2_contract(dsn)

    conn = await asyncpg.connect(dsn)
    try:
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

    current = _run_alembic("current", database_url=url)
    assert V2_CONTRACT in current.stdout

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM alerts") == 6
    finally:
        await conn.close()


# ======================================================================= whole chain


async def test_full_chain_down_to_base_and_back_up(scratch_db):
    """Every migration's downgrade, run in order against a populated database.

    This is what catches the same defect class in migrations other than the one that
    prompted a given fix.
    """
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", "head", database_url=url)
    await _seed_at_head(dsn)

    _run_alembic("downgrade", "base", database_url=url)

    for table in ("alerts", "rules", "watchlist", "universe", "scan_runs", "scanner_settings"):
        assert not await _table_exists(dsn, table), table

    _run_alembic("upgrade", "head", database_url=url)

    for table in ("alerts", "watchlist", "universe", "scan_runs", "scanner_settings"):
        assert await _table_exists(dsn, table), table
    # `rules` is created by the initial migration and dropped again at head.
    assert not await _table_exists(dsn, "rules")

    conn = await asyncpg.connect(dsn)
    try:
        # Down-to-base drops the tables, so the rows are gone. Asserted explicitly so
        # nobody mistakes this for data preservation.
        assert await conn.fetchval("SELECT count(*) FROM alerts") == 0
    finally:
        await conn.close()


async def test_stepwise_downgrade_of_the_scanner_tables_migration(scratch_db):
    """The `5c3b382f1d74` downgrade drops tables that `alerts` referenced via
    `scan_run_id`. Ordering only works because the later revisions drop that FK and
    column first; this pins that the downgrades compose."""
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", V2_CONTRACT, database_url=url)
    await _seed_at_v2_contract(dsn)

    _run_alembic("downgrade", SCANNER_TABLES, database_url=url)
    _run_alembic("downgrade", "-1", database_url=url)

    assert not await _table_exists(dsn, "scan_runs")
    assert await _table_exists(dsn, "alerts")

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM alerts") == 5
        assert not await _column_exists(dsn, "alerts", "scan_run_id")
    finally:
        await conn.close()

    _run_alembic("upgrade", "head", database_url=url)
    assert await _table_exists(dsn, "scan_runs")
