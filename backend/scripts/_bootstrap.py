"""Shared bootstrap for the CLI scripts.

Scripts are run as files (`uv run python scripts/foo.py`) rather than as modules, so the
backend directory has to be on `sys.path` before `app.*` imports resolve.
"""

import logging
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


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
