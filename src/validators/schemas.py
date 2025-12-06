"""Pydantic schemas for context validation."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class BudgetLevel(str, Enum):
    budget = "budget"
    normal = "normal"
    premium = "premium"


class Location(BaseModel):
    lat: float = Field(ge=-90.0, le=90.0)
    lon: float = Field(ge=-180.0, le=180.0)
    accuracy_m: Optional[float] = Field(default=None, ge=0)


class Preferences(BaseModel):
    vibe: Optional[str] = None
    budget: Optional[BudgetLevel] = None
    party_size: Optional[int] = Field(default=None, ge=1, le=50)
    tags: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class QueryContext(BaseModel):
    current_location: Optional[Location] = None
    preferences: Optional[Preferences] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    budget: Optional[BudgetLevel] = None


class AgentQuery(BaseModel):
    user_id: str
    session_id: Optional[str] = None
    query: str
    language: Optional[str] = None
    context: Optional[QueryContext] = None

    @field_validator("user_id")
    @classmethod
    def _validate_user_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("user_id cannot be empty")
        return value


class ValidatedContext(BaseModel):
    user_id: str
    session_id: str
    language: str
    location: Optional[Location] = None
    preferences: Optional[Preferences] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)
    validated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class ContextValidationError(Exception):
    """Custom error raised when the context is invalid."""

    def __init__(self, message: str, *, status_code: int = 422, field: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.field = field

    def as_dict(self) -> Dict[str, Any]:
        return {"message": self.message, "field": self.field, "status_code": self.status_code}

