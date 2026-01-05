"""Common Pydantic schemas."""

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel


class HealthStatus(str, Enum):
    """Health status options."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class HealthResponse(BaseModel):
    """Health check response."""

    status: HealthStatus
    timestamp: datetime
    version: Optional[str] = None
    alpaca_connected: Optional[bool] = None
    database_connected: Optional[bool] = None


class ErrorResponse(BaseModel):
    """Error response schema."""

    error: str
    message: str
    details: Optional[dict[str, Any]] = None
