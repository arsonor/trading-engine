"""Database configuration and session management (Postgres only)."""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()


def _build_engine_kwargs(database_url: str) -> dict:
    """Build kwargs for create_async_engine.

    Supabase's pooled endpoint (port 6543) runs pgBouncer in transaction mode, which
    forbids prepared statements. asyncpg caches statements by default, so we disable
    the cache when we detect the pooler host. Direct connections (port 5432) are fine.
    """
    kwargs: dict = {
        "echo": settings.debug,
        "future": True,
        "pool_pre_ping": True,
    }

    is_pooler = ":6543" in database_url or "pooler.supabase" in database_url
    if is_pooler:
        kwargs["connect_args"] = {
            # Disable asyncpg's prepared-statement cache for pgBouncer transaction mode.
            "statement_cache_size": 0,
            "prepared_statement_cache_size": 0,
        }

    return kwargs


engine = create_async_engine(settings.database_url, **_build_engine_kwargs(settings.database_url))

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    """Base class for all database models."""

    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session."""
    async with async_session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def init_db() -> None:
    """Ensure model metadata is registered.

    Schema is owned by Alembic — `alembic upgrade head` must be run before startup.
    This function stays as a no-op hook so the lifespan wiring is unchanged; it also
    imports models so Base.metadata is populated for tests that call create_all.
    """
    from app.models import Alert, Rule, Watchlist  # noqa: F401


async def check_db_connectivity() -> bool:
    """Cheap liveness probe used by /health."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def close_db() -> None:
    """Close database connections."""
    await engine.dispose()
