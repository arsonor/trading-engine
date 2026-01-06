"""Rule Pydantic schemas."""

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class RuleType(str, Enum):
    """Rule types."""

    PRICE = "price"
    VOLUME = "volume"
    GAP = "gap"
    TECHNICAL = "technical"


class RuleBase(BaseModel):
    """Base rule schema."""

    name: str = Field(..., min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    rule_type: RuleType
    config_yaml: str
    is_active: bool = True
    priority: int = 0


class RuleCreate(RuleBase):
    """Schema for creating a rule."""

    pass


class RuleUpdate(BaseModel):
    """Schema for updating a rule."""

    name: Optional[str] = Field(None, min_length=1, max_length=100)
    description: Optional[str] = Field(None, max_length=500)
    config_yaml: Optional[str] = None
    is_active: Optional[bool] = None
    priority: Optional[int] = None


class Rule(RuleBase):
    """Rule response schema."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    alerts_triggered: int = 0
    created_at: datetime
    updated_at: datetime
