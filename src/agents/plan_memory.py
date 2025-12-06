"""
Plan-specific memory management for tracking plan creation context.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from src.utils.logger import get_logger


@dataclass
class PlanContext:
    """Tracks context needed for plan creation."""

    duration: Optional[str] = None  # "2 hours", "evening", "full day"
    num_people: Optional[int] = None  # 1, 2, 5, etc.
    cities: List[str] = field(default_factory=list)  # ["Zaragoza"]
    place_types: List[str] = field(
        default_factory=list
    )  # ["bars", "restaurants"]
    vibe: Optional[str] = None  # "romantic", "adventure", "chill", "party"
    budget: Optional[str] = None  # "low", "medium", "high"
    transport: Optional[str] = None  # "walking", "car", "public"
    emotion_detected: Optional[str] = None  # "happy", "bored", "excited"
    user_questions_asked: List[str] = field(default_factory=list)
    created_at: datetime = field(default_factory=datetime.now)

    def is_plan_ready(self) -> Tuple[bool, List[str]]:
        """Check if we have minimum data for plan creation."""
        missing = []

        if not self.duration:
            missing.append("duration")
        if not self.num_people:
            missing.append("num_people")
        if not self.cities:
            missing.append("cities")
        if not self.place_types:
            missing.append("place_types")
        if not self.vibe:
            missing.append("vibe")

        return len(missing) == 0, missing

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict for caching."""
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


class PlanMemoryManager:
    """Manages context for plan creation within a session."""

    _instances: Dict[str, "PlanMemoryManager"] = {}
    MAX_TURNS: int = 50
    MAX_INSTANCES: int = 200

    def __init__(self):
        self.plan_context = PlanContext()
        self.conversation_history: List[Dict[str, str]] = []
        self.logger = get_logger("plan_memory")
        self.created_at = datetime.now()

    @classmethod
    def get_instance(cls, session_id: str) -> PlanMemoryManager:
        """Get or create a singleton instance for a session."""
        if session_id not in cls._instances:
            # Evict oldest instances if over capacity
            if len(cls._instances) >= cls.MAX_INSTANCES:
                # Drop 10 oldest to keep memory bounded
                oldest = sorted(
                    cls._instances.items(),
                    key=lambda item: item[1].created_at,
                )[:10]
                for key, _ in oldest:
                    cls._instances.pop(key, None)
            cls._instances[session_id] = cls()
        return cls._instances[session_id]

    def add_turn(self, user_query: str, agent_response: str):
        """Add conversation turn to memory."""
        self.conversation_history.append(
            {
                "user": user_query,
                "agent": agent_response,
                "timestamp": datetime.now().isoformat(),
            }
        )
        # Keep history bounded
        if len(self.conversation_history) > self.MAX_TURNS:
            # Remove oldest entries
            excess = len(self.conversation_history) - self.MAX_TURNS
            self.conversation_history = self.conversation_history[excess:]
        self.logger.debug("turn_added", turns_count=len(self.conversation_history))

    def update_plan_context(self, **kwargs):
        """Update plan context fields."""
        for key, value in kwargs.items():
            if hasattr(self.plan_context, key):
                setattr(self.plan_context, key, value)
        self.logger.debug("plan_context_updated", **kwargs)

    def mark_question_asked(self, question: str):
        """Track that we already asked this question."""
        self.plan_context.user_questions_asked.append(question)

    def has_asked_about(self, topic: str) -> bool:
        """Check if we already asked about something."""
        return any(
            topic.lower() in q.lower()
            for q in self.plan_context.user_questions_asked
        )

    def get_missing_for_plan(self) -> List[str]:
        """Get list of missing required fields."""
        _, missing = self.plan_context.is_plan_ready()
        return missing

    def get_context_summary(self) -> str:
        """Get human-readable summary of current plan context."""
        summary = []
        if self.plan_context.duration:
            summary.append(f"Duración: {self.plan_context.duration}")
        if self.plan_context.num_people:
            summary.append(f"Personas: {self.plan_context.num_people}")
        if self.plan_context.cities:
            summary.append(f"Ciudad(es): {', '.join(self.plan_context.cities)}")
        if self.plan_context.place_types:
            summary.append(
                f"Tipos: {', '.join(self.plan_context.place_types)}"
            )
        if self.plan_context.vibe:
            summary.append(f"Vibe: {self.plan_context.vibe}")
        return " | ".join(summary) if summary else "Información incompleta"

    def reset(self):
        """Reset plan context for new plan request."""
        self.plan_context = PlanContext()
        self.conversation_history = []
        self.logger.info("plan_memory_reset")

    @classmethod
    def clear_session(cls, session_id: str):
        """Clear memory for a given session to prevent leaks."""
        if session_id in cls._instances:
            cls._instances.pop(session_id, None)

