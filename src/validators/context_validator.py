"""Context validation logic (Step 1)."""

from __future__ import annotations

from typing import Any, Dict, Optional
from uuid import UUID, uuid4

from src.config import constants
from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger
from src.validators.schemas import (
    AgentQuery,
    ContextValidationError,
    Location,
    Preferences,
    QueryContext,
    ValidatedContext,
)


class ContextValidator:
    """Validate incoming conversational context before executing the agent pipeline."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("context-validator", settings=self.settings)

    async def validate_user(self, user_id: str) -> str:
        """Validate user_id. Now accepts any string format to support Auth0 IDs."""
        if not user_id or not isinstance(user_id, str) or len(user_id.strip()) == 0:
            self.logger.warning("invalid-user-id-empty", user_id=user_id)
            raise ContextValidationError("user_id cannot be empty", field="user_id")
        
        # Auth0 IDs can be: "auth0|123456", "google-oauth2|123456", etc.
        # UUIDs are also valid as strings
        return user_id.strip()

    async def validate_session(self, session_id: Optional[str]) -> str:
        if not session_id:
            generated = str(uuid4())
            self.logger.info("session-generated", session_id=generated)
            return generated
        try:
            UUID(session_id)
        except ValueError as exc:
            self.logger.warning("invalid-session-id", session_id=session_id)
            raise ContextValidationError("session_id must be a valid UUID", field="session_id") from exc
        return session_id

    async def validate_location(self, location: Optional[Location]) -> Optional[Location]:
        if location is None:
            return None
        if not (constants.LATITUDE_RANGE[0] <= location.lat <= constants.LATITUDE_RANGE[1]):
            raise ContextValidationError("Latitude is out of range", field="context.current_location.lat")
        if not (constants.LONGITUDE_RANGE[0] <= location.lon <= constants.LONGITUDE_RANGE[1]):
            raise ContextValidationError("Longitude is out of range", field="context.current_location.lon")
        return location

    async def validate_language(self, language: Optional[str]) -> str:
        normalized = (language or self.settings.default_language).lower()
        if normalized not in self.settings.supported_languages_list:
            self.logger.warning("unsupported-language", requested=normalized)
            raise ContextValidationError(
                f"Language '{normalized}' is not supported",
                field="language",
            )
        return normalized

    async def validate_preferences(self, preferences: Optional[Preferences]) -> Optional[Preferences]:
        if preferences is None:
            return None
        if preferences.party_size and preferences.party_size > 100:
            raise ContextValidationError("party_size exceeds allowed maximum", field="context.preferences.party_size")
        return preferences

    async def build_context(self, payload: AgentQuery) -> ValidatedContext:
        """Validate the entire payload and construct a normalized context."""

        context: QueryContext | None = payload.context

        validated = ValidatedContext(
            user_id=await self.validate_user(payload.user_id),
            session_id=await self.validate_session(payload.session_id),
            language=await self.validate_language(payload.language),
            location=await self.validate_location(context.current_location if context else None),
            preferences=await self.validate_preferences(context.preferences if context else None),
            metadata=self._build_metadata(payload),
        )

        self.logger.info(
            "context-validated",
            user_id=validated.user_id,
            session_id=validated.session_id,
            language=validated.language,
            has_location=bool(validated.location),
        )
        return validated

    def _build_metadata(self, payload: AgentQuery) -> Dict[str, Any]:
        metadata: Dict[str, Any] = {
            "stage": constants.CONTEXT_STAGE,
            "query_length": len(payload.query),
        }
        if payload.context and payload.context.metadata:
            metadata.update(payload.context.metadata)
        if payload.context and payload.context.budget:
            metadata["budget"] = payload.context.budget
        metadata["budget_mode"] = self.settings.budget_mode
        
        # Preserve chat_mode if present
        if payload.context and "chat_mode" in payload.context.metadata:
            metadata["chat_mode"] = payload.context.metadata["chat_mode"]
        
        return metadata

