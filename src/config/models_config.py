"""LLM routing metadata (populated in Step 2).

The structure mirrors the design guidelines from the architecture doc so
we can plug routing logic without refactoring.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class ModelProfile:
    """Profile for an LLM with cost/performance characteristics."""
    
    name: str
    provider: str
    cost_per_1k: float
    speed_score: float
    reasoning_score: float
    max_context_tokens: int | None = None


MODEL_PROFILES: Dict[str, ModelProfile] = {
    "gpt-4o-mini": ModelProfile(
        name="gpt-4o-mini",
        provider="openai",
        cost_per_1k=0.00015,
        speed_score=0.95,
        reasoning_score=0.6,
    ),
    "gpt-3.5-turbo": ModelProfile(
        name="gpt-3.5-turbo",
        provider="openai",
        cost_per_1k=0.0005,
        speed_score=0.9,
        reasoning_score=0.55,
    ),
    "gpt-4-turbo": ModelProfile(
        name="gpt-4-turbo",
        provider="openai",
        cost_per_1k=0.01,
        speed_score=0.75,
        reasoning_score=0.9,
    ),
    "gpt-4": ModelProfile(
        name="gpt-4",
        provider="openai",
        cost_per_1k=0.03,
        speed_score=0.5,
        reasoning_score=1.0,
    ),
    "claude-3": ModelProfile(
        name="claude-3",
        provider="anthropic",
        cost_per_1k=0.015,
        speed_score=0.8,
        reasoning_score=0.95,
    ),
}
