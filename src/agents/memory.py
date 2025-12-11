"""
Context memory management for maintaining conversation continuity.
Handles short-term (session) and long-term (user history) memory.

⚠️ DEPRECATED: This module is being replaced by conversation_buffer.py and context_builder.py
for a more robust, production-grade memory system.

For new code, use:
- ConversationBuffer: For loading/managing conversation context
- ContextBuilder: For building prompts from context
"""

from datetime import datetime
from typing import List, Optional
from uuid import UUID

from langchain_core.messages import AIMessage, HumanMessage, BaseMessage

from src.database.models import ConversationTurn
from src.database.repositories import ConversationRepository
from src.utils.cache_manager import CacheManager
from src.utils.logger import get_logger


class ConversationMemory:
    """
    Manages conversation memory with automatic summarization
    and context window management.
    """

    def __init__(
        self,
        repository: ConversationRepository,
        cache: Optional[CacheManager] = None,
        max_turns: int = 10,
        max_tokens: int = 2000,
    ):
        """
        Initialize memory manager.

        Args:
            repository: Database repository for persistence
            cache: Optional cache manager
            max_turns: Maximum turns to keep in context
            max_tokens: Approximate token limit for context
        """
        self.repository = repository
        self.cache = cache
        self.max_turns = max_turns
        self.max_tokens = max_tokens
        self.logger = get_logger("conversation_memory")

    def _build_messages_from_turns(self, turns: List[ConversationTurn]) -> List[BaseMessage]:
        """
        Build LangChain messages from conversation turns.
        
        Args:
            turns: List of conversation turns
            
        Returns:
            List of BaseMessage objects (HumanMessage, AIMessage)
        """
        messages = []
        if not turns:
            return messages

        for turn in turns:
            # Add user query
            messages.append(HumanMessage(content=turn.user_query))
            # Add agent response
            messages.append(AIMessage(content=turn.agent_response))

        return messages

    async def get_session_messages(
        self,
        session_id: UUID,
    ) -> List[BaseMessage]:
        """
        Get conversation history as a list of LangChain messages.

        Args:
            session_id: Session UUID

        Returns:
            List of BaseMessage objects (HumanMessage, AIMessage)
        """
        # Fetch from database
        turns = await self.repository.get_session_history(
            session_id=session_id,
            limit=self.max_turns,
        )

        messages = self._build_messages_from_turns(turns)

        self.logger.debug(
            "session_messages_retrieved",
            session_id=str(session_id),
            count=len(messages),
        )

        return messages

    def _build_context_string(
        self,
        turns: List[ConversationTurn],
        include_system_context: bool = True,
    ) -> str:
        """
        Build formatted context string from conversation turns.
        
        Args:
            turns: List of conversation turns
            include_system_context: Include system-level context
            
        Returns:
            Formatted context string
        """
        if not turns:
            return ""

        context_parts = []

        if include_system_context:
            context_parts.append("# Conversation History")
            context_parts.append(
                f"Session started: {turns[0].created_at.strftime('%Y-%m-%d %H:%M')}"
            )
            context_parts.append(f"Total turns: {len(turns)}\n")

        # Add turns (oldest to newest)
        for turn in turns:
            context_parts.append(f"User: {turn.user_query}")
            context_parts.append(f"Assistant: {turn.agent_response}")
            
            # Include places if available
            if turn.places_found and isinstance(turn.places_found, list) and len(turn.places_found) > 0:
                places_info = []
                for idx, place in enumerate(turn.places_found[:5], 1):  # Limit to first 5 places
                    place_name = place.get("name", "Unknown")
                    places_info.append(f"  {idx}. {place_name}")
                if places_info:
                    context_parts.append(f"Places mentioned: {', '.join(places_info)}")
            context_parts.append("")  # Empty line between turns

        # Join and truncate to respect token budget
        return self._truncate_context("\n".join(context_parts))

    async def _build_context_from_turns(
        self,
        turns: List[ConversationTurn],
        session_id: UUID,
        include_system_context: bool = True,
    ) -> str:
        """
        Build formatted context from turns with caching support.
        
        Args:
            turns: List of conversation turns
            session_id: Session UUID for cache key
            include_system_context: Include system-level context
            
        Returns:
            Formatted context string
        """
        # Try cache first
        if self.cache:
            cache_key = f"session_context:{session_id}"
            cached = await self.cache.get(cache_key)
            if cached:
                self.logger.debug("session_context_cache_hit", session_id=str(session_id))
                return cached

        context = self._build_context_string(turns, include_system_context)

        # Cache for short duration
        if self.cache and context:
            await self.cache.set(cache_key, context, ttl=300)  # 5 minutes

        return context

    async def get_session_context(
        self,
        session_id: UUID,
        include_system_context: bool = True,
    ) -> str:
        """
        Get formatted conversation context for a session.

        Args:
            session_id: Session UUID
            include_system_context: Include system-level context

        Returns:
            Formatted context string for LLM prompt
        """
        # Fetch from database
        turns = await self.repository.get_session_history(
            session_id=session_id,
            limit=self.max_turns,
        )

        context = await self._build_context_from_turns(turns, session_id, include_system_context)

        self.logger.debug(
            "session_context_built",
            session_id=str(session_id),
            turns=len(turns),
            chars=len(context),
        )

        return context

    def _extract_places_from_turns(
        self,
        turns: List[ConversationTurn],
        limit_turns: int = 3,
    ) -> List[dict]:
        """
        Extract places from conversation turns.
        
        Args:
            turns: List of conversation turns
            limit_turns: Number of recent turns to check for places
            
        Returns:
            List of places from recent turns, with turn context
        """
        if not turns:
            return []
        
        # Take only the most recent turns up to limit
        recent_turns = turns[:limit_turns]
        
        previous_places = []
        # Process turns from oldest to newest (reversed)
        for turn_idx, turn in enumerate(reversed(recent_turns), 1):
            if turn.places_found and isinstance(turn.places_found, list):
                for place_idx, place in enumerate(turn.places_found[:10], 1):  # Limit to 10 places per turn
                    place_with_context = place.copy()
                    place_with_context["_turn_number"] = turn_idx
                    place_with_context["_position_in_turn"] = place_idx
                    previous_places.append(place_with_context)
        
        return previous_places

    async def get_previous_places(
        self,
        session_id: UUID,
        limit_turns: int = 3,
    ) -> List[dict]:
        """
        Get places from previous conversation turns to help with references.
        
        Args:
            session_id: Session UUID
            limit_turns: Number of recent turns to check for places
            
        Returns:
            List of places from recent turns, with turn context
        """
        # Fetch recent turns
        turns = await self.repository.get_session_history(
            session_id=session_id,
            limit=limit_turns,
        )
        
        previous_places = self._extract_places_from_turns(turns, limit_turns)
        
        self.logger.debug(
            "previous_places_retrieved",
            session_id=str(session_id),
            places_count=len(previous_places),
            turns_checked=len(turns),
        )
        
        return previous_places

    async def get_user_patterns(
        self,
        user_id: UUID,
        hours_back: int = 24,
    ) -> dict:
        """
        Analyze user interaction patterns for personalization.

        Args:
            user_id: User UUID
            hours_back: Time window to analyze

        Returns:
            Dict with user patterns (favorite intentions, locations, etc.)
        """
        # Try cache first
        if self.cache:
            cache_key = f"user_patterns:{user_id}:{hours_back}"
            cached = await self.cache.get(cache_key)
            if cached:
                return cached

        # Fetch recent history
        turns = await self.repository.get_user_history(
            user_id=user_id,
            limit=50,
            hours_back=hours_back,
        )

        if not turns:
            return {
                "total_interactions": 0,
                "favorite_intention": None,
                "avg_confidence": 0,
                "common_languages": [],
            }

        # Analyze patterns
        intentions = {}
        languages = {}
        confidences = []

        for turn in turns:
            # Count intentions
            intentions[turn.intention] = intentions.get(turn.intention, 0) + 1

            # Count languages
            languages[turn.query_language] = (
                languages.get(turn.query_language, 0) + 1
            )

            # Collect confidences
            confidences.append(turn.confidence)

        # Build patterns
        patterns = {
            "total_interactions": len(turns),
            "favorite_intention": max(intentions, key=intentions.get)
            if intentions
            else None,
            "intention_distribution": intentions,
            "avg_confidence": sum(confidences) / len(confidences)
            if confidences
            else 0,
            "common_languages": sorted(
                languages.keys(), key=lambda k: languages[k], reverse=True
            ),
            "last_interaction": turns[0].created_at.isoformat()
            if turns
            else None,
        }

        # Cache for 1 hour
        if self.cache:
            await self.cache.set(cache_key, patterns, ttl=3600)

        self.logger.debug(
            "user_patterns_analyzed",
            user_id=str(user_id),
            interactions=len(turns),
        )

        return patterns

    async def summarize_session(
        self,
        session_id: UUID,
        llm_summarize_fn: Optional[callable] = None,
    ) -> str:
        """
        Create a summary of a conversation session.

        Args:
            session_id: Session UUID
            llm_summarize_fn: Optional LLM function for intelligent summarization

        Returns:
            Summary string
        """
        turns = await self.repository.get_session_history(
            session_id=session_id,
            limit=100,  # Get all turns
        )

        if not turns:
            return "No conversation history found."

        if llm_summarize_fn:
            # Use LLM for intelligent summarization
            conversation_text = "\n\n".join(
                [
                    f"User: {t.user_query}\nAssistant: {t.agent_response}"
                    for t in turns
                ]
            )
            summary = await llm_summarize_fn(conversation_text)
        else:
            # Simple summary
            intention_counts = {}
            for turn in turns:
                intention_counts[turn.intention] = (
                    intention_counts.get(turn.intention, 0) + 1
                )

            summary = (
                f"Session Summary:\n"
                f"- Total interactions: {len(turns)}\n"
                f"- Intentions: {intention_counts}\n"
                f"- Duration: {turns[0].created_at} to {turns[-1].created_at}\n"
            )

        self.logger.info(
            "session_summarized",
            session_id=str(session_id),
            turns=len(turns),
        )

        return summary

    def _estimate_tokens(self, text: str) -> int:
        """
        Rough token estimation (1 token ≈ 4 characters).

        Args:
            text: Text to estimate

        Returns:
            Approximate token count
        """
        return len(text) // 4

    def _truncate_context(self, context: str) -> str:
        """
        Truncate context to fit within token limit.

        Args:
            context: Full context string

        Returns:
            Truncated context
        """
        estimated_tokens = self._estimate_tokens(context)

        if estimated_tokens <= self.max_tokens:
            return context

        # Truncate from the beginning (keep most recent context)
        char_limit = self.max_tokens * 4
        truncated = context[-char_limit:]

        # Try to truncate at a turn boundary
        turn_marker = "\nUser:"
        if turn_marker in truncated:
            first_turn = truncated.index(turn_marker)
            truncated = truncated[first_turn:]

        self.logger.debug(
            "context_truncated",
            original_tokens=estimated_tokens,
            new_tokens=self._estimate_tokens(truncated),
        )

        return truncated


class MemoryManager:
    """
    High-level memory manager that combines short-term and long-term memory.
    
    ✅ UPDATED: Now uses ConversationBuffer and ContextBuilder for robust memory management.
    """

    def __init__(
        self,
        repository: ConversationRepository,
        cache: Optional[CacheManager] = None,
    ):
        """
        Initialize memory manager.

        Args:
            repository: Database repository
            cache: Optional cache manager
        """
        # Old implementation (kept for backward compatibility during migration)
        self.conversation_memory = ConversationMemory(
            repository=repository,
            cache=cache,
        )
        
        # New implementation (production-grade)
        from src.agents.conversation_buffer import ConversationBuffer
        from src.agents.context_builder import ContextBuilder
        
        self.buffer = ConversationBuffer(
            repository=repository,
            cache=cache,
        )
        self.builder = ContextBuilder()
        
        self.logger = get_logger("memory_manager")

    async def build_agent_context(
        self,
        user_id: UUID,
        session_id: UUID,
        current_query: str,
        include_history: bool = True,
        include_patterns: bool = False,
        current_language: str = "es",
    ) -> dict:
        """
        Build comprehensive context for agent.
        
        ✅ UPDATED: Now uses ConversationBuffer for robust, production-grade memory.

        Args:
            user_id: User UUID
            session_id: Session UUID
            current_query: Current user query
            include_history: Include conversation history
            include_patterns: Include user pattern analysis
            current_language: Language for responses

        Returns:
            Dict with context components (backward compatible + enhanced)
        """
        # Load context using new ConversationBuffer
        conv_context = await self.buffer.load_context(
            user_id=user_id,
            session_id=session_id,
            current_query=current_query,
            current_language=current_language,
        )
        
        # Build agent context using ContextBuilder
        context = self.builder.build_agent_context_dict(conv_context)
        
        # Get user patterns if requested (optional feature)
        if include_patterns:
            context["user_patterns"] = (
                await self.conversation_memory.get_user_patterns(user_id)
            )
        else:
            context["user_patterns"] = None
        
        self.logger.info(
            "agent_context_built_v2",
            user_id=str(user_id),
            session_id=str(session_id),
            has_history=len(conv_context.recent_turns) > 0,
            has_patterns=context["user_patterns"] is not None,
            previous_places_count=len(context.get("previous_places", [])),
            estimated_tokens=conv_context.estimated_tokens,
        )

        return context
    
    async def invalidate_session_cache(self, session_id: UUID):
        """
        Invalidate cache for a session (call after new message saved).
        
        Args:
            session_id: Session UUID to invalidate
        """
        await self.buffer.invalidate_cache(session_id)

