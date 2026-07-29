"""Alembic migration environment configuration.

Two things here are load-bearing and were previously wrong:

1. **The engine is built with the same pgBouncer rules as the app runtime.** This file
   used to call `async_engine_from_config`, which read `sqlalchemy.url` out of the ini
   and applied none of the connect_args in `app/core/database.py`. Against Supabase's
   transaction pooler that failed with
   `DuplicatePreparedStatementError: prepared statement "__asyncpg_stmt_1__" already
   exists`. Both paths now import `app/core/db_connect.py`; see that module for why
   three separate settings are needed.

2. **The URL never goes through the ini.** `config.set_main_option()` writes into a
   configparser, where a `%` in a password is read as interpolation syntax and raises
   `InterpolationSyntaxError` — a failure mode that only shows up for whoever happens
   to get a `%` in their generated credentials. The DSN is passed straight to
   `create_async_engine` instead.

Migrations also take a Postgres advisory lock, so two instances starting at once
serialize instead of racing to apply the same revision. See `do_run_migrations`.
"""

import asyncio
import logging
from logging.config import fileConfig

from sqlalchemy import pool, text
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import context

# Import settings and models
from app.config import get_settings
from app.core.database import Base
from app.core.db_connect import asyncpg_connect_args, describe_target, is_transaction_pooler

# Import all models to register them with Base.metadata
from app.models.alert import Alert  # noqa: F401
from app.models.api_budget import ApiBudget  # noqa: F401
from app.models.premarket_volume_profile import PremarketVolumeProfile  # noqa: F401
from app.models.reference_data import ReferenceData  # noqa: F401
from app.models.scan_run import ScanRun  # noqa: F401
from app.models.scanner_settings import ScannerSettings  # noqa: F401
from app.models.universe import Universe  # noqa: F401
from app.models.watchlist import Watchlist  # noqa: F401

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

settings = get_settings()

# MIGRATION_DATABASE_URL when set, else DATABASE_URL. Deliberately NOT written back into
# the ini — see the module docstring on `%` in passwords.
MIGRATION_URL = settings.effective_migration_url

# Arbitrary but stable 64-bit key. Any process running migrations for THIS application
# uses the same number; nothing else in the database should pick it by accident.
MIGRATION_LOCK_KEY = 8_274_193_045_112_337

# add your model's MetaData object here for 'autogenerate' support
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode (SQL script generation, no DBAPI needed)."""
    context.configure(
        url=MIGRATION_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations under an advisory lock.

    `alembic upgrade head` runs from the web service's startCommand, so every container
    start races every other one. Alembic takes no lock of its own: two instances can
    both read the current revision, both decide the same migration is pending, and both
    try to apply it.

    `pg_advisory_xact_lock` (transaction-scoped, not session-scoped) is used because a
    session-scoped lock is meaningless through a transaction-mode pooler, where the
    session is not stable. The lock is released when the migration transaction commits
    or rolls back — including if the process is killed.

    This blocks rather than failing fast: a second instance waits for the first to
    finish and then finds nothing to do, which is the correct outcome for migrate-on-boot.
    """
    context.configure(connection=connection, target_metadata=target_metadata)

    with context.begin_transaction():
        connection.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"), {"lock_key": MIGRATION_LOCK_KEY}
        )
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in 'online' mode with an async engine."""
    logger.info("Running migrations against %s", describe_target(MIGRATION_URL))
    if is_transaction_pooler(MIGRATION_URL):
        logger.warning(
            "Migration target is the TRANSACTION pooler (port 6543). This works — the "
            "connection is configured for pgBouncer — but Supabase intends the SESSION "
            "pooler (port 5432) for DDL. Set MIGRATION_DATABASE_URL to the 5432 endpoint."
        )

    connectable = create_async_engine(
        MIGRATION_URL,
        # NullPool: migrations are a single short-lived connection, and SQLAlchemy's
        # docs require it when talking to pgBouncer to avoid accumulating statements.
        poolclass=pool.NullPool,
        # The whole point of this fix — identical rules to the app runtime.
        connect_args=asyncpg_connect_args(MIGRATION_URL),
    )

    try:
        async with connectable.connect() as connection:
            await connection.run_sync(do_run_migrations)
    finally:
        await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
