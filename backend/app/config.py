"""Application configuration using Pydantic settings.

Phase 0 (v2): Postgres-only. FMP and scanner threshold settings are wired here
so later phases can consume them without a config revisit; they are unused this phase.
"""

from functools import lru_cache
from typing import Annotated, List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


def _normalize_database_url(v: str) -> str:
    """Normalize a Postgres URL to the asyncpg driver form.

    Accepts:
      - postgres://...
      - postgresql://...
      - postgresql+asyncpg://... (already normalized)
    """
    if v.startswith("postgres://"):
        return v.replace("postgres://", "postgresql+asyncpg://", 1)
    if v.startswith("postgresql://") and "+asyncpg" not in v:
        return v.replace("postgresql://", "postgresql+asyncpg://", 1)
    return v


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # Ignore frontend-specific VITE_* variables
    )

    # Application
    app_name: str = "Trading Alert Engine"
    app_env: str = "development"
    debug: bool = True
    log_level: str = "INFO"

    # Server
    host: str = "0.0.0.0"
    port: int = 8000

    # Database — Postgres only. No default; must be provided.
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:postgres@localhost:5432/trading_engine",
        description="Async Postgres DSN. SQLite is not supported.",
    )

    @field_validator("database_url", mode="after")
    @classmethod
    def validate_database_url(cls, v: str) -> str:
        v = _normalize_database_url(v)
        if not v.startswith("postgresql+asyncpg://"):
            raise ValueError(
                "DATABASE_URL must be a Postgres async DSN "
                "('postgresql+asyncpg://...' or 'postgresql://...' / 'postgres://...' "
                "which are auto-normalized). SQLite is no longer supported (v2)."
            )
        return v

    # Alpaca API — v1 legacy. Kept until the scanner (Phase 2) is proven; not used by v2 code.
    alpaca_api_key: str = ""
    alpaca_secret_key: str = ""
    alpaca_base_url: str = "https://paper-api.alpaca.markets"
    alpaca_data_feed: str = "iex"

    # FMP — v2 data provider. Wired here; consumed by Phase 1+.
    fmp_api_key: str = ""
    fmp_base_url: str = "https://financialmodelingprep.com"

    # Scanner thresholds (tunable without redeploy). Consumed by Phase 2+.
    scanner_timezone: str = "America/New_York"
    scanner_enabled: bool = True
    scan_float_max: int = 75_000_000
    scan_avg_volume_min: int = 500_000
    scan_gap_min: float = 3.0
    scan_gap_max: float = 15.0
    scan_rvol_min: float = 10.0
    scan_upside_min: float = 5.5
    scan_price_floor: float = 2.0

    # CORS — Vercel frontend origin(s) go here in production, comma-separated or JSON array.
    # NoDecode disables pydantic-settings' JSON pre-parse so a plain comma list works.
    cors_origins: Annotated[List[str], NoDecode] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]

    # Rules directory (v1 rule engine; will be repurposed for scanner threshold overrides)
    rules_directory: str = "rules"

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v):
        """Accept either a JSON array or a comma-separated string in env."""
        if isinstance(v, str):
            s = v.strip()
            if s.startswith("["):
                import json

                return json.loads(s)
            return [origin.strip() for origin in s.split(",") if origin.strip()]
        return v

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def is_development(self) -> bool:
        return self.app_env == "development"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
