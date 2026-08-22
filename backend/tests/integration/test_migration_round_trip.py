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
from datetime import date, datetime
from pathlib import Path

import asyncpg
import pytest

from app.config import get_settings

BACKEND_DIR = Path(__file__).parents[2]

# Revisions this file navigates between.
SCANNER_TABLES = "5c3b382f1d74"  # universe, reference_data, scan_runs, api_budget
V2_CONTRACT = "0ca0181ab014"  # v2 alert columns added; v1 columns still present
PHASE_35 = "c653a931ecaf"  # v1 columns dropped, symbol -> ticker, rules dropped
WATCHLIST_DROP = "544a7fbf3445"  # watchlist dropped
RLS = "dbdf5784db31"  # RLS enabled on all public tables
PHASE_4B = "b008d4bf3a18"  # api_budget.bytes_used + universe_runs
PHASE_4C = "ae74a2cbe20c"  # alerts decision-time provenance
SCAN_MODE = "3d1177ad1103"  # scan_runs.mode
SCAN_OBSERVATIONS = "a71f4c9e2d05"  # scan_observations, the Phase 5 evidence table (numbered Phase 6 when the migration was written)
SESSION_VOLUME = "c92e7b1a4f38"  # premarket_session_volume, incremental profiles

# Revision-specific tests name the revision they exercise instead of using "head" or
# a relative "-1". Both of those silently retarget the moment a new migration lands on
# top — which has already caused two false failures in this file.

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


async def _seed_v2_alerts(dsn: str) -> dict:
    """Seed v2-only alerts. Valid from PHASE_35 onward, where `alerts` uses
    `ticker` and carries no v1 columns."""
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
    """Downgrade must succeed on a populated database and restore the previous schema.

    Pinned to PHASE_35 rather than `head` so it keeps testing THIS migration as later
    revisions land on top."""
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", PHASE_35, database_url=url)
    seeded = await _seed_v2_alerts(dsn)

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
    _run_alembic("upgrade", PHASE_35, database_url=url)
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


async def test_watchlist_drop_round_trips_on_populated_data(scratch_db):
    """The watchlist held user-entered rows, so its drop is tested with rows present."""
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", PHASE_35, database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        for symbol in ("AAPL", "TSLA", "NVDA"):
            await conn.execute(
                "INSERT INTO watchlist (symbol, added_at, is_active, notes) "
                "VALUES ($1, now(), true, 'watching')",
                symbol,
            )
    finally:
        await conn.close()

    result = _run_alembic("upgrade", WATCHLIST_DROP, database_url=url)
    assert "Dropping `watchlist` with 3 row(s)" in result.stdout + result.stderr
    assert not await _table_exists(dsn, "watchlist")

    # Downgrade restores the table, empty — the rows are gone, as documented.
    _run_alembic("downgrade", "-1", database_url=url)
    assert await _table_exists(dsn, "watchlist")

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval("SELECT count(*) FROM watchlist") == 0
    finally:
        await conn.close()

    _run_alembic("upgrade", "head", database_url=url)
    assert not await _table_exists(dsn, "watchlist")


async def test_watchlist_drop_is_safe_when_the_table_is_already_gone(scratch_db):
    """The migration must not fail on a database where the table was removed by hand."""
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", PHASE_35, database_url=url)
    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute("DROP TABLE watchlist")
    finally:
        await conn.close()

    result = _run_alembic("upgrade", "head", database_url=url)
    assert "already absent" in result.stdout + result.stderr


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
    await _seed_v2_alerts(dsn)

    _run_alembic("downgrade", "base", database_url=url)

    for table in ("alerts", "rules", "watchlist", "universe", "scan_runs", "scanner_settings"):
        assert not await _table_exists(dsn, table), table

    _run_alembic("upgrade", "head", database_url=url)

    for table in ("alerts", "universe", "scan_runs", "scanner_settings"):
        assert await _table_exists(dsn, table), table
    # Both are created by earlier migrations and dropped again by the time we reach
    # head: `rules` in Phase 3.5, `watchlist` in the revision after it.
    assert not await _table_exists(dsn, "rules")
    assert not await _table_exists(dsn, "watchlist")

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


# ======================================================================= Phase 4B


async def test_phase_4b_round_trips_on_populated_data(scratch_db):
    """`bytes_used` and `universe_runs` survive a downgrade/upgrade cycle with rows present.

    The failure this guards is the one that has bitten this project twice: adding a NOT
    NULL column to a populated table. `api_budget.bytes_used` carries `server_default='0'`
    precisely so existing rows do not violate the constraint, and an empty-database test
    would never notice if that default were dropped.
    """
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]

    _run_alembic("upgrade", f"{PHASE_4B}-1", database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        # Populate api_budget BEFORE the column exists — the whole point of the test.
        await conn.execute(
            "INSERT INTO api_budget (budget_date, provider, calls_used, created_at, "
            "updated_at) VALUES ($1, 'fmp', 4321, now(), now())",
            date(2026, 8, 5),
        )
    finally:
        await conn.close()

    _run_alembic("upgrade", PHASE_4B, database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT calls_used, bytes_used FROM api_budget WHERE budget_date = $1",
            date(2026, 8, 5),
        )
        assert row["calls_used"] == 4321, "existing usage must survive the migration"
        assert row["bytes_used"] == 0, "server_default must backfill, not fail"

        await conn.execute(
            "INSERT INTO universe_runs (started_at, status, universe_size, "
            "stage1_eligible, calls_used, bytes_used) "
            "VALUES (now(), 'completed', 3948, 554, 11, 9427999)"
        )
        assert await conn.fetchval("SELECT count(*) FROM universe_runs") == 1
    finally:
        await conn.close()

    # Down: the lossy direction. It must succeed WITH rows present, not just when empty.
    _run_alembic("downgrade", f"{PHASE_4B}-1", database_url=url)
    assert not await _table_exists(dsn, "universe_runs")

    conn = await asyncpg.connect(dsn)
    try:
        cols = await conn.fetch(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name = 'api_budget'"
        )
        assert "bytes_used" not in {c["column_name"] for c in cols}
        # The pre-existing row is untouched by the column drop.
        assert await conn.fetchval(
            "SELECT calls_used FROM api_budget WHERE budget_date = $1", date(2026, 8, 5)
        ) == 4321
    finally:
        await conn.close()

    _run_alembic("upgrade", "head", database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval(
            "SELECT bytes_used FROM api_budget WHERE budget_date = $1", date(2026, 8, 5)
        ) == 0, "re-upgrade restarts the counter; there is no source to reconstruct it"
    finally:
        await conn.close()


async def test_phase_4b_enables_rls_on_universe_runs(scratch_db):
    """A new public table without RLS is world-writable through the Supabase anon key.
    tests/integration/test_rls.py enforces this globally; this pins it to the migration."""
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]
    _run_alembic("upgrade", PHASE_4B, database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval(
            "SELECT relrowsecurity FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace WHERE n.nspname = 'public' AND relname = 'universe_runs'"
        ) is True
    finally:
        await conn.close()


async def test_phase_4c_provenance_round_trips_on_populated_alerts(scratch_db):
    """Adding provenance to a populated `alerts` table, and dropping it again.

    All three columns are nullable with no default, so neither direction needs a backfill.
    What a downgrade destroys is the provenance itself — the bars those alerts were
    computed from have since settled to different values, so it cannot be reconstructed.
    The schema round-trips; the information does not.
    """
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]
    _run_alembic("upgrade", f"{PHASE_4C}-1", database_url=url)

    await _seed_v2_alerts(dsn)

    _run_alembic("upgrade", PHASE_4C, database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT gap_pct, bars_settled_through, provisional_bars_excluded, "
            "profile_sessions_sampled FROM alerts WHERE ticker = 'ADBE'"
        )
        assert row["gap_pct"] == 7.0, "the pre-existing alert survives untouched"
        assert row["bars_settled_through"] is None
        # And the columns actually accept what the scanner writes.
        await conn.execute(
            "UPDATE alerts SET bars_settled_through = $1, provisional_bars_excluded = 2, "
            "profile_sessions_sampled = 20 WHERE ticker = 'ADBE'",
            datetime(2026, 8, 6, 9, 15),
        )
        assert await conn.fetchval(
            "SELECT profile_sessions_sampled FROM alerts WHERE ticker = 'ADBE'"
        ) == 20
    finally:
        await conn.close()

    _run_alembic("downgrade", f"{PHASE_4C}-1", database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        cols = {c["column_name"] for c in await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'alerts'"
        )}
        assert "bars_settled_through" not in cols
        assert await conn.fetchval("SELECT gap_pct FROM alerts WHERE ticker = 'ADBE'") == 7.0
    finally:
        await conn.close()

    _run_alembic("upgrade", "head", database_url=url)


async def test_scan_mode_round_trips_on_populated_scan_runs(scratch_db):
    """Adding `scan_runs.mode` to a table that already has rows, and dropping it again.

    Nullable with no default, so neither direction needs a backfill. Historical rows keep
    NULL rather than being defaulted to `live`: their mode was never recorded, and
    asserting one would invent a fact about runs nobody observed.
    """
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]
    _run_alembic("upgrade", f"{SCAN_MODE}-1", database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO scan_runs (started_at, finished_at, status, profile, "
            "api_calls_used) VALUES (now(), now(), 'completed', 'production', 42)"
        )
    finally:
        await conn.close()

    _run_alembic("upgrade", SCAN_MODE, database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        row = await conn.fetchrow(
            "SELECT api_calls_used, mode FROM scan_runs WHERE profile = 'production'"
        )
        assert row["api_calls_used"] == 42, "the pre-existing run survives untouched"
        assert row["mode"] is None, "history is not retro-labelled with a mode it never had"

        # And the column accepts what the scanner writes.
        await conn.execute("UPDATE scan_runs SET mode = 'observation'")
        assert await conn.fetchval("SELECT mode FROM scan_runs LIMIT 1") == "observation"
    finally:
        await conn.close()

    _run_alembic("downgrade", f"{SCAN_MODE}-1", database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        cols = {c["column_name"] for c in await conn.fetch(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'scan_runs'"
        )}
        assert "mode" not in cols
        assert await conn.fetchval("SELECT api_calls_used FROM scan_runs LIMIT 1") == 42
    finally:
        await conn.close()

    _run_alembic("upgrade", "head", database_url=url)


async def test_scan_observations_round_trips_on_populated_scan_runs(scratch_db):
    """Creating `scan_observations` beside populated `scan_runs`, and dropping it again.

    The table is new and empty on arrival, so the upgrade cannot break existing rows. The
    two things worth pinning are that the FK accepts a real `scan_runs.id` and that the
    downgrade does not take the runs with it — `ON DELETE CASCADE` points from
    observations to runs, and a reader could easily assume it points the other way.
    """
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]
    _run_alembic("upgrade", f"{SCAN_OBSERVATIONS}-1", database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        run_id = await conn.fetchval(
            "INSERT INTO scan_runs (started_at, finished_at, status, profile, "
            "api_calls_used) VALUES (now(), now(), 'completed', 'production', 118) "
            "RETURNING id"
        )
    finally:
        await conn.close()

    _run_alembic("upgrade", SCAN_OBSERVATIONS, database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO scan_observations (scan_run_id, session_date, observed_at, "
            "ticker, stage_reached, rejection_reason, gap_pct, is_candidate, "
            "volume_avg_20d, price_close_yesterday) "
            "VALUES ($1, $2, $3, 'FLAT', 'stage_2_momentum', 'gap outside band', 1.0, "
            "false, 1000000, 100.0)",
            run_id,
            date(2026, 8, 14),
            datetime(2026, 8, 14, 9, 25),
        )
        row = await conn.fetchrow(
            "SELECT gap_pct, rvol_pct, rejection_reason FROM scan_observations "
            "WHERE ticker = 'FLAT'"
        )
        assert row["gap_pct"] == 1.0, "the number that caused the rejection is stored"
        assert row["rvol_pct"] is None, "NULL means never evaluated, not zero"

        # A new public table without RLS is world-writable through the Supabase anon key.
        assert await conn.fetchval(
            "SELECT relrowsecurity FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace WHERE n.nspname = 'public' "
            "AND relname = 'scan_observations'"
        ) is True

        # The unique constraint is what makes a retried write converge.
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO scan_observations (scan_run_id, session_date, observed_at, "
                "ticker, stage_reached) VALUES ($1, $2, $3, 'FLAT', 'stage_2_momentum')",
                run_id,
                date(2026, 8, 14),
                datetime(2026, 8, 14, 9, 25),
            )
    finally:
        await conn.close()

    _run_alembic("downgrade", f"{SCAN_OBSERVATIONS}-1", database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval(
            "SELECT to_regclass('public.scan_observations') IS NULL"
        ) is True
        assert await conn.fetchval(
            "SELECT api_calls_used FROM scan_runs WHERE id = $1", run_id
        ) == 118, "dropping the observations must not touch the runs they pointed at"
    finally:
        await conn.close()

    _run_alembic("upgrade", "head", database_url=url)


async def test_premarket_session_volume_round_trips_with_a_populated_profile(scratch_db):
    """Adding per-session curves beside an existing profile, and dropping them again.

    The averages in `premarket_volume_profile` must survive both directions untouched:
    they are the RVOL denominator, and the scanner keeps running off them whether or not
    the incremental machinery exists.
    """
    url, dsn = scratch_db["sqlalchemy_url"], scratch_db["dsn"]
    _run_alembic("upgrade", f"{SESSION_VOLUME}-1", database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO universe (ticker, is_active, created_at, updated_at) "
            "VALUES ('INCR', true, now(), now())"
        )
        await conn.execute(
            "INSERT INTO premarket_volume_profile (ticker, bucket_minute, "
            "avg_cumulative_volume, sessions_sampled, computed_at) "
            "VALUES ('INCR', 0, 1234.5, 20, now())"
        )
    finally:
        await conn.close()

    _run_alembic("upgrade", SESSION_VOLUME, database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        await conn.execute(
            "INSERT INTO premarket_session_volume (ticker, session_date, buckets, "
            "bars_used) VALUES ('INCR', $1, $2, 2)",
            date(2026, 8, 14),
            '{"0": 100.0, "5": 150.0}',
        )
        # JSON keys are strings on the way out; the model's bucket_map() undoes that.
        stored = await conn.fetchval(
            "SELECT buckets FROM premarket_session_volume WHERE ticker = 'INCR'"
        )
        assert '"0"' in stored or "'0'" in stored

        assert await conn.fetchval(
            "SELECT relrowsecurity FROM pg_class c JOIN pg_namespace n "
            "ON n.oid = c.relnamespace WHERE n.nspname = 'public' "
            "AND relname = 'premarket_session_volume'"
        ) is True

        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO premarket_session_volume (ticker, session_date, buckets) "
                "VALUES ('INCR', $1, $2)",
                date(2026, 8, 14),
                "{}",
            )
    finally:
        await conn.close()

    _run_alembic("downgrade", f"{SESSION_VOLUME}-1", database_url=url)

    conn = await asyncpg.connect(dsn)
    try:
        assert await conn.fetchval(
            "SELECT to_regclass('public.premarket_session_volume') IS NULL"
        ) is True
        assert await conn.fetchval(
            "SELECT avg_cumulative_volume FROM premarket_volume_profile "
            "WHERE ticker = 'INCR'"
        ) == 1234.5, "the denominator the scanner divides by is untouched"
    finally:
        await conn.close()

    _run_alembic("upgrade", "head", database_url=url)
