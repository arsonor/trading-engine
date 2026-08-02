"""Database configuration and session management (Postgres only)."""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings
from app.core.db_connect import engine_kwargs

settings = get_settings()

# pgBouncer handling lives in `app/core/db_connect.py` so Alembic uses the identical
# rule. It previously lived here, which is exactly how `alembic/env.py` ended up with a
# connection that had none of it.
engine = create_async_engine(
    settings.database_url,
    **engine_kwargs(settings.database_url, echo=settings.debug),
)

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
    from app.models import (  # noqa: F401
        Alert,
        ApiBudget,
        PremarketVolumeProfile,
        ReferenceData,
        ScannerSettings,
        ScanRun,
        Universe,
    )


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
