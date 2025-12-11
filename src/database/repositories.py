"""Data access layer for agent persistence."""

from datetime import datetime, timedelta
from typing import List, Optional
from uuid import UUID

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import AgentMetrics, Chat, ConversationTurn, UserPreference
from src.utils.logger import get_logger

logger = get_logger("repositories")


class ConversationRepository:
    """Repository for conversation turn operations."""

    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session

    async def check_connection(self) -> bool:
        """Check if database connection is active."""
        try:
            await self.session.execute(select(1))
            return True
        except Exception as e:
            logger.error("database_connection_check_failed", error=str(e))
            return False

    async def save_turn(
        self,
        user_id: str,  # Changed to str to support Auth0 IDs
        session_id: UUID,
        user_query: str,
        query_language: str,
        intention: str,
        confidence: float,
        complexity: str,
        model_used: str,
        model_provider: str,
        agent_response: str,
        places_found: Optional[list] = None,
        processing_time_ms: int = 0,
        tool_calls: int = 0,
        reasoning_steps: int = 0,
        extra_metadata: Optional[dict] = None,
    ) -> ConversationTurn:
        """
        Save a conversation turn to database.

        Args:
            user_id: User ID (string, supports Auth0 IDs)
            session_id: Session UUID
            user_query: User's query text
            query_language: Language code (es, en, ca, gl)
            intention: Classified intention
            confidence: Classification confidence
            complexity: Query complexity (low, medium, high)
            model_used: LLM model name
            model_provider: LLM provider (openai, anthropic)
            agent_response: Agent's response text
            places_found: Optional list of places
            processing_time_ms: Processing time in milliseconds
            tool_calls: Number of tool calls
            reasoning_steps: Number of reasoning steps
            extra_metadata: Optional metadata dict

        Returns:
            Created ConversationTurn instance
        """
        turn = ConversationTurn(
            user_id=user_id,
            session_id=session_id,
            user_query=user_query,
            query_language=query_language,
            intention=intention,
            confidence=confidence,
            complexity=complexity,
            model_used=model_used,
            model_provider=model_provider,
            agent_response=agent_response,
            places_found=places_found,
            processing_time_ms=processing_time_ms,
            tool_calls=tool_calls,
            reasoning_steps=reasoning_steps,
            extra_metadata=extra_metadata,
        )

        self.session.add(turn)
        await self.session.flush()

        logger.info(
            "conversation_turn_saved",
            turn_id=str(turn.id),
            user_id=str(user_id),
            intention=intention,
        )

        return turn

    async def get_session_history(
        self,
        session_id: UUID,
        limit: int = 20,
    ) -> List[ConversationTurn]:
        """
        Get conversation history for a session.

        Args:
            session_id: Session UUID
            limit: Maximum number of turns to return

        Returns:
            List of conversation turns (newest first)
        """
        stmt = (
            select(ConversationTurn)
            .where(ConversationTurn.session_id == session_id)
            .order_by(desc(ConversationTurn.created_at))
            .limit(limit)
        )

        result = await self.session.execute(stmt)
        turns = result.scalars().all()

        logger.debug(
            "session_history_retrieved",
            session_id=str(session_id),
            count=len(turns),
        )

        return list(reversed(turns))  # Return oldest first

    async def get_user_history(
        self,
        user_id: str,  # Changed to str to support Auth0 IDs
        limit: int = 50,
        hours_back: Optional[int] = None,
    ) -> List[ConversationTurn]:
        """
        Get conversation history for a user.

        Args:
            user_id: User ID (string, supports Auth0 IDs)
            limit: Maximum number of turns to return
            hours_back: Optional time window (e.g., 24 for last 24 hours)

        Returns:
            List of conversation turns (newest first)
        """
        stmt = select(ConversationTurn).where(ConversationTurn.user_id == user_id)

        if hours_back:
            cutoff = datetime.utcnow() - timedelta(hours=hours_back)
            stmt = stmt.where(ConversationTurn.created_at >= cutoff)

        stmt = stmt.order_by(desc(ConversationTurn.created_at)).limit(limit)

        result = await self.session.execute(stmt)
        turns = result.scalars().all()

        logger.debug(
            "user_history_retrieved",
            user_id=str(user_id),
            count=len(turns),
            hours_back=hours_back,
        )

        return list(turns)

    async def get_turn_by_id(self, turn_id: UUID) -> Optional[ConversationTurn]:
        """Get a specific conversation turn by ID."""
        stmt = select(ConversationTurn).where(ConversationTurn.id == turn_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class ChatRepository:
    """Repository for chat/conversation operations."""

    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session

    async def create_chat(
        self,
        user_id: str,  # Changed to str to support Auth0 IDs
        session_id: UUID,
        title: str,
        mode: Optional[str] = None,
    ) -> Chat:
        """
        Create a new chat or return existing one if session_id already exists.

        Args:
            user_id: User UUID
            session_id: Session UUID (must be unique)
            title: Chat title
            mode: Optional chat mode (explore/plan)

        Returns:
            Created or existing Chat instance
        """
        # Check if chat already exists for this session_id
        existing_chat = await self.get_chat_by_session_id(session_id)
        
        if existing_chat:
            logger.info(
                "chat_already_exists",
                chat_id=str(existing_chat.id),
                session_id=str(session_id),
            )
            return existing_chat
        
        # Create new chat
        chat = Chat(
            user_id=user_id,
            session_id=session_id,
            title=title,
            mode=mode,
        )

        self.session.add(chat)
        await self.session.flush()

        logger.info(
            "chat_created",
            chat_id=str(chat.id),
            user_id=str(user_id),
            session_id=str(session_id),
            title=title,
        )

        return chat

    async def get_chat_by_session_id(self, session_id: UUID) -> Optional[Chat]:
        """Get chat by session_id."""
        stmt = select(Chat).where(Chat.session_id == session_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_chat_by_id(self, chat_id: UUID) -> Optional[Chat]:
        """Get chat by ID."""
        stmt = select(Chat).where(Chat.id == chat_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_user_chats(
        self,
        user_id: str,  # Changed to str to support Auth0 IDs
        limit: int = 50,
        offset: int = 0,
    ) -> List[Chat]:
        """
        Get all chats for a user, ordered by most recently updated.

        Args:
            user_id: User ID (string, supports Auth0 IDs)
            limit: Maximum number of chats to return
            offset: Number of chats to skip

        Returns:
            List of Chat instances (newest first)
        """
        stmt = (
            select(Chat)
            .where(Chat.user_id == user_id)
            .order_by(desc(Chat.updated_at))
            .limit(limit)
            .offset(offset)
        )

        result = await self.session.execute(stmt)
        chats = result.scalars().all()

        logger.debug(
            "user_chats_retrieved",
            user_id=str(user_id),
            count=len(chats),
        )

        return list(chats)

    async def update_chat_title(self, chat_id: UUID, title: str) -> Optional[Chat]:
        """
        Update chat title.

        Args:
            chat_id: Chat UUID
            title: New title

        Returns:
            Updated Chat instance or None if not found
        """
        chat = await self.get_chat_by_id(chat_id)
        if not chat:
            return None

        chat.title = title
        chat.updated_at = func.now()
        await self.session.flush()

        logger.info("chat_title_updated", chat_id=str(chat_id), title=title)

        return chat

    async def update_chat_updated_at(self, chat_id: UUID) -> None:
        """Update chat's updated_at timestamp."""
        chat = await self.get_chat_by_id(chat_id)
        if chat:
            chat.updated_at = func.now()
            await self.session.flush()

    async def delete_chat(self, chat_id: UUID, user_id: str) -> bool:  # user_id changed to str
        """
        Delete a chat (only if it belongs to the user).

        Args:
            chat_id: Chat UUID
            user_id: User UUID (for security)

        Returns:
            True if deleted, False if not found or not authorized
        """
        chat = await self.get_chat_by_id(chat_id)
        if not chat or chat.user_id != user_id:
            return False

        await self.session.delete(chat)
        await self.session.flush()

        logger.info("chat_deleted", chat_id=str(chat_id), user_id=str(user_id))

        return True


class UserPreferenceRepository:
    """Repository for user preference operations."""

    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session

    async def get_or_create(
        self,
        user_id: str,  # Changed to str to support Auth0 IDs
        default_language: str = "es",
    ) -> UserPreference:
        """
        Get existing preferences or create new ones.

        Args:
            user_id: User ID (string, supports Auth0 IDs)
            default_language: Default language if creating new

        Returns:
            UserPreference instance
        """
        stmt = select(UserPreference).where(UserPreference.user_id == user_id)
        result = await self.session.execute(stmt)
        preference = result.scalar_one_or_none()

        if not preference:
            preference = UserPreference(
                user_id=user_id,
                preferred_language=default_language,
            )
            self.session.add(preference)
            await self.session.flush()

            logger.info(
                "user_preference_created",
                user_id=str(user_id),
                language=default_language,
            )

        return preference

    async def update_preferences(
        self,
        user_id: str,  # Changed to str to support Auth0 IDs
        preferred_language: Optional[str] = None,
        preferred_model: Optional[str] = None,
        budget_mode: Optional[bool] = None,
        favorite_categories: Optional[list] = None,
    ) -> UserPreference:
        """
        Update user preferences.

        Args:
            user_id: User ID (string, supports Auth0 IDs)
            preferred_language: Optional language to set
            preferred_model: Optional model preference
            budget_mode: Optional budget mode flag
            favorite_categories: Optional favorite categories

        Returns:
            Updated UserPreference instance
        """
        preference = await self.get_or_create(user_id)

        if preferred_language is not None:
            preference.preferred_language = preferred_language

        if preferred_model is not None:
            preference.preferred_model = preferred_model

        if budget_mode is not None:
            preference.budget_mode = budget_mode

        if favorite_categories is not None:
            preference.favorite_categories = favorite_categories

        preference.interaction_count += 1
        await self.session.flush()

        logger.info("user_preference_updated", user_id=str(user_id))

        return preference


class MetricsRepository:
    """Repository for agent metrics operations."""

    def __init__(self, session: AsyncSession):
        """Initialize with database session."""
        self.session = session

    async def record_query(
        self,
        intention: str,
        model_used: str,
        processing_time_ms: int,
        confidence: float,
        estimated_cost: float,
    ) -> None:
        """
        Record a query for aggregation.

        Args:
            intention: Query intention
            model_used: Model used
            processing_time_ms: Processing time
            confidence: Confidence score
            estimated_cost: Estimated cost in USD
        """
        now = datetime.utcnow()
        date = now.date()
        hour = now.hour

        # Try to find existing metric for this hour
        stmt = select(AgentMetrics).where(
            AgentMetrics.date == date,
            AgentMetrics.hour == hour,
        )
        result = await self.session.execute(stmt)
        metric = result.scalar_one_or_none()

        if not metric:
            # Create new metric with all fields initialized
            metric = AgentMetrics(
                date=date,
                hour=hour,
                total_queries=0,
                avg_processing_time_ms=0.0,
                avg_confidence=0.0,
                search_count=0,
                recommend_count=0,
                plan_count=0,
                chitchat_count=0,
                model_usage={},
                estimated_cost_usd=0.0,
            )
            self.session.add(metric)

        # Ensure all counters are initialized (defensive programming)
        if metric.total_queries is None:
            metric.total_queries = 0
        if metric.avg_processing_time_ms is None:
            metric.avg_processing_time_ms = 0.0
        if metric.avg_confidence is None:
            metric.avg_confidence = 0.0
        if metric.search_count is None:
            metric.search_count = 0
        if metric.recommend_count is None:
            metric.recommend_count = 0
        if metric.plan_count is None:
            metric.plan_count = 0
        if metric.chitchat_count is None:
            metric.chitchat_count = 0
        if metric.estimated_cost_usd is None:
            metric.estimated_cost_usd = 0.0
        if metric.model_usage is None:
            metric.model_usage = {}

        # Update aggregations
        metric.total_queries += 1

        # Update rolling averages
        n = metric.total_queries
        metric.avg_processing_time_ms = (
            (metric.avg_processing_time_ms * (n - 1)) + processing_time_ms
        ) / n
        metric.avg_confidence = ((metric.avg_confidence * (n - 1)) + confidence) / n

        # Update intention counts
        if intention == "SEARCH":
            metric.search_count += 1
        elif intention == "RECOMMEND":
            metric.recommend_count += 1
        elif intention == "PLAN":
            metric.plan_count += 1
        elif intention == "CHITCHAT":
            metric.chitchat_count += 1

        # Update model usage
        metric.model_usage[model_used] = metric.model_usage.get(model_used, 0) + 1

        # Update costs
        metric.estimated_cost_usd += estimated_cost

        await self.session.flush()

        logger.debug(
            "metrics_recorded",
            date=str(date),
            hour=hour,
            intention=intention,
            model=model_used,
        )

    async def get_metrics_summary(
        self,
        days_back: int = 7,
    ) -> dict:
        """
        Get aggregated metrics summary.

        Args:
            days_back: Number of days to look back

        Returns:
            Summary dict with aggregated metrics
        """
        cutoff = datetime.utcnow() - timedelta(days=days_back)

        stmt = select(AgentMetrics).where(AgentMetrics.date >= cutoff.date())

        result = await self.session.execute(stmt)
        metrics = result.scalars().all()

        if not metrics:
            return {
                "total_queries": 0,
                "avg_processing_time_ms": 0,
                "avg_confidence": 0,
                "total_cost_usd": 0,
                "by_intention": {},
                "by_model": {},
            }

        total_queries = sum(m.total_queries for m in metrics)
        total_cost = sum(m.estimated_cost_usd for m in metrics)

        # Weighted averages
        weighted_time = sum(
            m.avg_processing_time_ms * m.total_queries for m in metrics
        )
        weighted_confidence = sum(m.avg_confidence * m.total_queries for m in metrics)

        avg_time = weighted_time / total_queries if total_queries > 0 else 0
        avg_confidence = weighted_confidence / total_queries if total_queries > 0 else 0

        # Aggregate by intention
        by_intention = {
            "SEARCH": sum(m.search_count for m in metrics),
            "RECOMMEND": sum(m.recommend_count for m in metrics),
            "PLAN": sum(m.plan_count for m in metrics),
            "CHITCHAT": sum(m.chitchat_count for m in metrics),
        }

        # Aggregate by model
        by_model = {}
        for m in metrics:
            if m.model_usage:
                for model, count in m.model_usage.items():
                    by_model[model] = by_model.get(model, 0) + count

        return {
            "total_queries": total_queries,
            "avg_processing_time_ms": round(avg_time, 2),
            "avg_confidence": round(avg_confidence, 3),
            "total_cost_usd": round(total_cost, 4),
            "by_intention": by_intention,
            "by_model": by_model,
            "days_analyzed": days_back,
        }

