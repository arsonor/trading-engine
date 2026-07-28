"""Postgres connection configuration shared by the app runtime and Alembic.

This module exists because the rule below was previously implemented in
`app/core/database.py` only, and `alembic/env.py` built its own engine that bypassed it.
Migrations against Supabase's transaction pooler then failed with::

    asyncpg.exceptions.DuplicatePreparedStatementError:
    prepared statement "__asyncpg_stmt_1__" already exists

**Two copies of this rule will drift**, so it lives here and both callers import it.
This module deliberately has no import side effects — no engine is created — so
`alembic/env.py` can use it without instantiating the runtime engine.

## Why pgBouncer breaks asyncpg

Supabase offers three endpoints, and they are not interchangeable:

| Endpoint            | Host / port                            | pgBouncer mode | Prepared statements |
|---------------------|----------------------------------------|----------------|---------------------|
| Direct              | `db.<ref>.supabase.co:5432`            | none           | safe                |
| Session pooler      | `aws-<region>.pooler.supabase.com:5432`| session        | safe (dedicated server conn per client session) |
| Transaction pooler  | `aws-<region>.pooler.supabase.com:6543`| transaction    | **unsafe**          |

In *transaction* mode pgBouncer hands a server connection back to the pool after every
transaction, so consecutive statements from one client can land on different server
connections — and, worse, two different client connections can be multiplexed onto the
*same* server connection. asyncpg names its prepared statements per-connection with a
simple counter (`__asyncpg_stmt_1__`, `__asyncpg_stmt_2__`, …), so two clients both
starting at 1 on a shared server connection collide.

Three settings are needed together, and each fixes a different half of the problem:

* ``statement_cache_size=0`` — stops asyncpg caching statements across transactions,
  which would otherwise go stale when pgBouncer moves you to another server connection.
* ``prepared_statement_cache_size=0`` — the same, for SQLAlchemy's own layer of caching.
* ``prepared_statement_name_func`` — gives every statement a UUID name so two clients
  sharing a server connection cannot collide. **This is the one that was missing**;
  the two cache settings alone do not prevent the name clash, because asyncpg still
  prepares each statement, it just stops keeping it.

This is the workaround SQLAlchemy documents for pgBouncer; see
`sqlalchemy.dialects.postgresql.asyncpg`, "Prepared Statement Name with PGBouncer".

Applied to the session pooler too. It is not strictly required there, but it costs
nothing measurable and means one rule covers every Supabase endpoint rather than a
second rule that has to be right about which port implies which pooling mode.
"""

from urllib.parse import urlsplit
from uuid import uuid4

# Supabase's transaction pooler always listens here; the session pooler uses 5432.
TRANSACTION_POOLER_PORT = ":6543"
# Both pooled endpoints resolve through this host, direct connections do not.
POOLER_HOST_MARKER = "pooler.supabase"


def is_pgbouncer(database_url: str) -> bool:
    """Whether this URL goes through pgBouncer (either pooling mode)."""
    return TRANSACTION_POOLER_PORT in database_url or POOLER_HOST_MARKER in database_url


def is_transaction_pooler(database_url: str) -> bool:
    """Whether this URL is the *transaction*-mode pooler, where DDL is risky."""
    return TRANSACTION_POOLER_PORT in database_url


def asyncpg_connect_args(database_url: str) -> dict:
    """connect_args needed for this URL. Empty for direct (non-pooled) connections."""
    if not is_pgbouncer(database_url):
        return {}
    return {
        # asyncpg's own statement cache — stale after pgBouncer reassigns the server conn.
        "statement_cache_size": 0,
        # SQLAlchemy's asyncpg-dialect cache — same reasoning.
        "prepared_statement_cache_size": 0,
        # Unique names so multiplexed clients cannot collide on __asyncpg_stmt_N__.
        "prepared_statement_name_func": lambda: f"__asyncpg_{uuid4()}__",
    }


def engine_kwargs(database_url: str, *, echo: bool = False, pool_pre_ping: bool = True) -> dict:
    """Kwargs for `create_async_engine` on the app-runtime path."""
    kwargs: dict = {"echo": echo, "future": True, "pool_pre_ping": pool_pre_ping}
    connect_args = asyncpg_connect_args(database_url)
    if connect_args:
        kwargs["connect_args"] = connect_args
    return kwargs


def describe_target(database_url: str) -> str:
    """Human-readable, credential-free description of a DSN, safe to log.

    Migration failures are diagnosed by knowing *which endpoint* was targeted, and that
    has to be loggable without putting the password in Render's log stream.
    """
    try:
        parts = urlsplit(database_url)
    except ValueError:  # pragma: no cover - malformed URL
        return "<unparseable database url>"

    host = parts.hostname or "?"
    port = parts.port
    database = (parts.path or "/").lstrip("/") or "?"

    if is_transaction_pooler(database_url):
        kind = "Supabase transaction pooler (pgBouncer, transaction mode)"
    elif is_pgbouncer(database_url):
        kind = "Supabase session pooler (pgBouncer, session mode)"
    else:
        kind = "direct connection (no pooler)"

    return f"{host}:{port or '?'}/{database} — {kind}"
