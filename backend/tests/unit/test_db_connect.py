"""Tests for the shared Postgres connection configuration.

This module exists because the rule it encodes was previously duplicated — implemented
in `app/core/database.py` and absent from `alembic/env.py`, which is what produced
`DuplicatePreparedStatementError` on Render. These tests pin the rule itself and, just
as importantly, pin that **both** callers use it.
"""

from pathlib import Path

import pytest

from app.config import Settings
from app.core.db_connect import (
    asyncpg_connect_args,
    describe_target,
    engine_kwargs,
    is_pgbouncer,
    is_transaction_pooler,
)

BACKEND_DIR = Path(__file__).parents[2]

# NOTE: `alembic/env.py` is deliberately NOT imported here. Importing it executes the
# migration run at module scope. It is asserted against as source text instead.

# A password distinctive enough that a leak into a log line is unmistakable.
SECRET = "hunter2SECRETpw"

# The endpoint shapes this project actually connects to.
LOCAL_DOCKER = "postgresql+asyncpg://postgres:postgres@localhost:5433/trading_engine"
SUPABASE_DIRECT = f"postgresql+asyncpg://postgres:{SECRET}@db.abcdefgh.supabase.co:5432/postgres"
SUPABASE_SESSION = (
    f"postgresql+asyncpg://postgres.abcdefgh:{SECRET}"
    "@aws-0-eu-central-1.pooler.supabase.com:5432/postgres"
)
SUPABASE_TRANSACTION = (
    f"postgresql+asyncpg://postgres.abcdefgh:{SECRET}"
    "@aws-0-eu-central-1.pooler.supabase.com:6543/postgres"
)


# ------------------------------------------------------------------ classification


@pytest.mark.parametrize(
    "url,pgbouncer,transaction",
    [
        (LOCAL_DOCKER, False, False),
        (SUPABASE_DIRECT, False, False),
        (SUPABASE_SESSION, True, False),
        (SUPABASE_TRANSACTION, True, True),
    ],
)
def test_endpoint_classification(url, pgbouncer, transaction):
    assert is_pgbouncer(url) is pgbouncer
    assert is_transaction_pooler(url) is transaction


def test_direct_connections_get_no_special_args():
    """Non-pooled connections must not pay for pgBouncer workarounds."""
    assert asyncpg_connect_args(LOCAL_DOCKER) == {}
    assert asyncpg_connect_args(SUPABASE_DIRECT) == {}
    assert "connect_args" not in engine_kwargs(LOCAL_DOCKER)


# ------------------------------------------------------------------ the actual fix


@pytest.mark.parametrize("url", [SUPABASE_SESSION, SUPABASE_TRANSACTION])
def test_pooled_connections_get_all_three_settings(url):
    """All three are required, and each fixes a different half of the problem — see the
    module docstring in app/core/db_connect.py."""
    args = asyncpg_connect_args(url)

    assert args["statement_cache_size"] == 0
    assert args["prepared_statement_cache_size"] == 0
    assert callable(args["prepared_statement_name_func"])


def test_prepared_statement_names_are_unique():
    """The setting that was missing. Without it, two clients multiplexed onto one
    pgBouncer server connection both prepare `__asyncpg_stmt_1__` and the second fails
    with DuplicatePreparedStatementError."""
    name_func = asyncpg_connect_args(SUPABASE_TRANSACTION)["prepared_statement_name_func"]

    names = {name_func() for _ in range(500)}

    assert len(names) == 500
    assert all(n.startswith("__asyncpg_") and n.endswith("__") for n in names)


def test_name_func_does_not_reuse_asyncpg_counter_format():
    """Must not collide with asyncpg's own `__asyncpg_stmt_N__` namespace either."""
    name_func = asyncpg_connect_args(SUPABASE_TRANSACTION)["prepared_statement_name_func"]

    assert "stmt" not in name_func()


# ------------------------------------------------------------------ engine kwargs


def test_engine_kwargs_carry_the_connect_args_for_pooled_urls():
    kwargs = engine_kwargs(SUPABASE_TRANSACTION, echo=False)

    assert kwargs["connect_args"]["statement_cache_size"] == 0
    assert kwargs["pool_pre_ping"] is True


def test_engine_kwargs_respect_echo():
    assert engine_kwargs(LOCAL_DOCKER, echo=True)["echo"] is True
    assert engine_kwargs(LOCAL_DOCKER, echo=False)["echo"] is False


# ------------------------------------------------------------------ safe logging


@pytest.mark.parametrize(
    "url,expected_fragment",
    [
        (LOCAL_DOCKER, "direct connection"),
        (SUPABASE_DIRECT, "direct connection"),
        (SUPABASE_SESSION, "session mode"),
        (SUPABASE_TRANSACTION, "transaction mode"),
    ],
)
def test_describe_target_names_the_endpoint_kind(url, expected_fragment):
    assert expected_fragment in describe_target(url)


@pytest.mark.parametrize("url", [SUPABASE_SESSION, SUPABASE_TRANSACTION, SUPABASE_DIRECT])
def test_describe_target_never_leaks_the_password(url):
    """This string goes into Render's log stream."""
    described = describe_target(url)

    assert SECRET not in described
    assert "@" not in described


def test_describe_target_survives_a_malformed_url():
    assert describe_target("not a url at all")


# ------------------------------------------------------------------ migration URL


def test_migration_url_falls_back_to_database_url():
    settings = Settings(database_url=LOCAL_DOCKER)

    assert settings.migration_database_url == ""
    assert settings.effective_migration_url == LOCAL_DOCKER


def test_migration_url_overrides_database_url_when_set():
    """The two-URL model: runtime on the transaction pooler, DDL on the session pooler."""
    settings = Settings(
        database_url=SUPABASE_TRANSACTION, migration_database_url=SUPABASE_SESSION
    )

    assert settings.effective_migration_url == SUPABASE_SESSION
    assert is_transaction_pooler(settings.database_url)
    assert not is_transaction_pooler(settings.effective_migration_url)


def test_migration_url_is_normalised_like_database_url():
    settings = Settings(
        database_url=LOCAL_DOCKER,
        migration_database_url="postgres://postgres:pw@db.abc.supabase.co:5432/postgres",
    )

    assert settings.effective_migration_url.startswith("postgresql+asyncpg://")


def test_a_non_postgres_migration_url_is_rejected():
    with pytest.raises(ValueError, match="MIGRATION_DATABASE_URL"):
        Settings(database_url=LOCAL_DOCKER, migration_database_url="mysql://root@localhost/db")


# ------------------------------------------------------------------ both callers wired


def test_alembic_env_uses_the_shared_helper():
    """The regression guard. `alembic/env.py` used to build its own engine via
    `async_engine_from_config`, which applied none of this."""
    source = (BACKEND_DIR / "alembic" / "env.py").read_text(encoding="utf-8")

    assert "asyncpg_connect_args" in source
    assert "connect_args=asyncpg_connect_args(" in source
    # The bypassing call must be gone, not merely supplemented. Checked as a call and an
    # import rather than a bare substring — the docstring names it to explain the history.
    assert "async_engine_from_config(" not in source
    assert "import async_engine_from_config" not in source


def test_alembic_env_uses_the_migration_url_and_not_the_ini():
    """`config.set_main_option` puts the DSN through configparser, where a `%` in a
    password raises InterpolationSyntaxError."""
    source = (BACKEND_DIR / "alembic" / "env.py").read_text(encoding="utf-8")

    assert "effective_migration_url" in source
    assert 'config.set_main_option("sqlalchemy.url"' not in source


def test_runtime_engine_uses_the_shared_helper():
    source = (BACKEND_DIR / "app" / "core" / "database.py").read_text(encoding="utf-8")

    assert "from app.core.db_connect import engine_kwargs" in source
    # The old private duplicate must not come back.
    assert "_build_engine_kwargs" not in source
