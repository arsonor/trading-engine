"""Shared bootstrap for the CLI scripts.

Scripts are run as files (`uv run python scripts/foo.py`) rather than as modules, so the
backend directory has to be on `sys.path` before `app.*` imports resolve.

Also provides `run_cli()`, which every script uses instead of `asyncio.run()` so pooled
database connections are closed deterministically — see its docstring.
"""

import asyncio
import logging
import sys
from collections.abc import Coroutine
from pathlib import Path
from typing import Any

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def run_cli(coro: Coroutine[Any, Any, int]) -> int:
    """Run a CLI coroutine and dispose the database engine before the loop closes.

    `asyncio.run(main())` on its own leaves the engine's pooled connections to be torn
    down by garbage collection — after the event loop has already closed. Against local
    Docker Postgres that is invisible. Against Supabase (TLS) it prints a
    `Fatal error on SSL transport` / `RuntimeError: Event loop is closed` traceback on
    every run, because the SSL transport's finaliser tries to write a close-notify to a
    dead loop.

    The work has already committed by then, so it is cosmetic — but a tool that must be
    trusted when it reports failure cannot spend every successful run training its
    operator to scroll past tracebacks.

    Disposal happens inside the loop and in a `finally`, so it runs on the error path
    too. Note this is deterministic cleanup, not warning suppression: the traceback
    disappears because the connections are actually closed.
    """

    async def _runner() -> int:
        try:
            return await coro
        finally:
            # Imported here so `sys.path` is already set up and scripts that never touch
            # the database do not pay for creating the engine.
            from app.core.database import close_db

            await close_db()

    return asyncio.run(_runner())


def configure_logging(verbose: bool = False) -> None:
    """Human-readable structured logs for CLI runs."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    if not verbose:
        _silence_sql_echo()


def _silence_sql_echo() -> None:
    """Turn off SQLAlchemy's statement echo for CLI runs.

    `DEBUG=true` in .env sets `echo=True` on the engine, which buries the report under
    every SELECT. `engine.echo = False` also drops the extra handler echo installs, so
    the per-ticker log lines are not printed twice.
    """
    from app.core.database import engine

    engine.echo = False
    for name in ("sqlalchemy", "sqlalchemy.engine", "sqlalchemy.engine.Engine"):
        logger = logging.getLogger(name)
        logger.setLevel(logging.WARNING)
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
