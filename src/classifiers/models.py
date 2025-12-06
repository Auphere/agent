"""Data models for the classifier module."""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field


class IntentType(str, Enum):
    SEARCH = "SEARCH"
    RECOMMEND = "RECOMMEND"
    PLAN = "PLAN"
    CHITCHAT = "CHITCHAT"


class IntentResult(BaseModel):
    """Structured output for intent classification."""

    intention: IntentType = Field(..., description="The classified intent category.")
    confidence: float = Field(..., description="Confidence score between 0.0 and 1.0")
    reasoning: str = Field(..., description="Brief explanation of why this intent was chosen.")
    complexity: Literal["low", "medium", "high"] = Field(
        "low", description="Estimated complexity of satisfying the request."
    )

