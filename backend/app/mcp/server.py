"""FastMCP server for Trading Engine.

This module defines the MCP server that exposes trading engine functionality
to AI assistants like Claude.

Usage:
    # Run directly
    uv run python -m app.mcp.server

    # Or via MCP CLI
    uv run mcp run app/mcp/server.py
"""

from contextlib import asynccontextmanager
from typing import AsyncIterator

from mcp.server.fastmcp import FastMCP
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.mcp.config import get_mcp_settings, setup_mcp_logging

# Initialize settings and logging
settings = get_mcp_settings()
logger = setup_mcp_logging()

# Create the MCP server
mcp = FastMCP(
    name=settings.server_name,
    instructions="Trading Engine MCP server for managing alerts, rules, and market analysis.",
)

# Database engine (lazy initialization)
_engine = None
_session_maker = None


def _get_engine():
    """Get or create the database engine."""
    global _engine
    if _engine is None:
        _engine = create_async_engine(
            settings.database_url,
            echo=False,  # Don't echo SQL to stdout (breaks STDIO)
            future=True,
        )
    return _engine


def _get_session_maker():
    """Get or create the session maker."""
    global _session_maker
    if _session_maker is None:
        _session_maker = async_sessionmaker(
            _get_engine(),
            class_=AsyncSession,
            expire_on_commit=False,
        )
    return _session_maker


@asynccontextmanager
async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Get a database session for MCP tools.

    Usage:
        async with get_db_session() as session:
            # Use session for database operations
            result = await session.execute(query)
    """
    session_maker = _get_session_maker()
    async with session_maker() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def cleanup():
    """Cleanup database connections on shutdown."""
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None
        logger.info("Database connections closed")


def _register_tools_and_resources():
    """Register all tools and resources with the MCP server.

    This is called lazily to avoid circular imports.
    Tools use decorators that reference the mcp server instance.
    """
    # Import tools - these register via decorators
    # Import resources - these register via decorators
    from app.mcp.resources import data  # noqa: F401
    from app.mcp.tools import alerts, analysis, rules, watchlist  # noqa: F401

    logger.info("MCP tools and resources registered")


# Defer registration until needed
_tools_registered = False


def ensure_tools_registered():
    """Ensure tools are registered (called before server runs)."""
    global _tools_registered
    if not _tools_registered:
        _register_tools_and_resources()
        _tools_registered = True


logger.info(f"MCP server '{settings.server_name}' v{settings.server_version} initialized")


def main():
    """Run the MCP server."""
    import asyncio

    logger.info("Starting MCP server...")

    # Register tools before running
    ensure_tools_registered()

    try:
        mcp.run()
    except KeyboardInterrupt:
        logger.info("Server interrupted")
    finally:
        asyncio.run(cleanup())


if __name__ == "__main__":
    main()
