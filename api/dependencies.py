"""FastAPI dependency providers."""

from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import Depends

from src.agents.memory import MemoryManager
from src.classifiers.intent_classifier import IntentClassifier
from src.config.settings import Settings, get_settings
from src.database import (
    ChatRepository,
    ConversationRepository,
    MetricsRepository,
    UserPreferenceRepository,
    get_db_session,
)
from src.i18n import Translator, get_translator
from src.routers.llm_router import LLMRouter
from src.utils.cache_manager import CacheManager, get_cache_manager
from src.utils.metrics import MetricsCollector, get_metrics_collector
from src.validators.context_validator import ContextValidator


# Core validators and classifiers
def get_context_validator(
    settings: Settings = Depends(get_settings),
) -> ContextValidator:
    """Get context validator instance."""
    return ContextValidator(settings=settings)


def get_intent_classifier(
    settings: Settings = Depends(get_settings),
) -> IntentClassifier:
    """Get intent classifier instance."""
    return IntentClassifier(settings=settings)


def get_llm_router(
    settings: Settings = Depends(get_settings),
) -> LLMRouter:
    """Get LLM router instance."""
    return LLMRouter(settings=settings)


# Database repositories
def get_conversation_repo(
    db: AsyncSession = Depends(get_db_session),
) -> ConversationRepository:
    """Get conversation repository."""
    return ConversationRepository(db)


def get_user_preference_repo(
    db: AsyncSession = Depends(get_db_session),
) -> UserPreferenceRepository:
    """Get user preference repository."""
    return UserPreferenceRepository(db)


def get_metrics_repo(
    db: AsyncSession = Depends(get_db_session),
) -> MetricsRepository:
    """Get metrics repository."""
    return MetricsRepository(db)


def get_chat_repo(
    db: AsyncSession = Depends(get_db_session),
) -> ChatRepository:
    """Get chat repository."""
    return ChatRepository(db)


# Utility services
async def get_cache() -> CacheManager:
    """Get cache manager instance."""
    return await get_cache_manager()


def get_translator_instance(
    settings: Settings = Depends(get_settings),
) -> Translator:
    """Get translator instance."""
    return get_translator(settings)


def get_metrics() -> MetricsCollector:
    """Get metrics collector instance."""
    return get_metrics_collector()


# Memory manager
async def get_memory_manager(
    conversation_repo: ConversationRepository = Depends(get_conversation_repo),
    cache: CacheManager = Depends(get_cache),
) -> MemoryManager:
    """Get memory manager instance."""
    return MemoryManager(
        repository=conversation_repo,
        cache=cache,
    )
