"""MCP server configuration.

This module provides configuration specific to the MCP server,
separate from the main FastAPI application configuration.
"""

import logging
import sys
from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class MCPSettings(BaseSettings):
    """MCP server settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Allow other env vars in .env file
    )

    # Server identification
    server_name: str = "trading-engine"
    server_version: str = "1.0.0"

    # Database
    database_url: str = "sqlite+aiosqlite:///./trading_engine.db"

    @field_validator("database_url", mode="after")
    @classmethod
    def transform_database_url(cls, v: str) -> str:
        """Transform database URL for async compatibility."""
        if v.startswith("postgres://"):
            return v.replace("postgres://", "postgresql+asyncpg://", 1)
        if v.startswith("postgresql://") and "+asyncpg" not in v:
            return v.replace("postgresql://", "postgresql+asyncpg://", 1)
        return v

    # Logging - MCP uses STDIO, so we must log to stderr or file
    log_level: str = "INFO"
    log_file: str | None = None  # If None, logs to stderr


@lru_cache
def get_mcp_settings() -> MCPSettings:
    """Get cached MCP settings instance."""
    return MCPSettings()


def setup_mcp_logging() -> logging.Logger:
    """Set up logging for MCP server.

    IMPORTANT: MCP uses STDIO for communication, so we MUST NOT write
    to stdout. All logs go to stderr or a file.
    """
    settings = get_mcp_settings()
    logger = logging.getLogger("mcp.trading_engine")
    logger.setLevel(getattr(logging, settings.log_level.upper()))

    # Remove existing handlers
    logger.handlers.clear()

    # Create formatter
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    if settings.log_file:
        # Log to file
        handler = logging.FileHandler(settings.log_file)
    else:
        # Log to stderr (NOT stdout!)
        handler = logging.StreamHandler(sys.stderr)

    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger
