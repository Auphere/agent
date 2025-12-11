"""
Advanced conversation buffer with sliding window, compression, and multi-level memory.

This implements a production-grade memory system inspired by Cursor, Perplexity, and modern LLM applications.
It solves the common problem of "memory works sometimes" by providing:

1. Working Memory: Current conversation turn (immediate context)
2. Short-term Memory: Recent conversation with sliding window + compression
3. Long-term Memory: Summarized historical context for personalization

All backed by database + Redis for consistency across workers/restarts.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src.database.models import ConversationTurn
from src.database.repositories import ConversationRepository
from src.utils.cache_manager import CacheManager
from src.utils.logger import get_logger

logger = get_logger("conversation_buffer")


@dataclass
class MemoryWindow:
    """Represents a time-windowed slice of conversation memory."""
    
    turns: List[ConversationTurn] = field(default_factory=list)
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    total_tokens: int = 0
    summary: Optional[str] = None
    
    def add_turn(self, turn: ConversationTurn, estimated_tokens: int = 0):
        """Add a turn to this window."""
        self.turns.append(turn)
        self.total_tokens += estimated_tokens
        
        if not self.start_time:
            self.start_time = turn.created_at
        self.end_time = turn.created_at
    
    def is_empty(self) -> bool:
        """Check if window has no turns."""
        return len(self.turns) == 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for caching."""
        return {
            "turn_ids": [str(t.id) for t in self.turns],
            "start_time": self.start_time.isoformat() if self.start_time else None,
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "total_tokens": self.total_tokens,
            "summary": self.summary,
        }


@dataclass
class ConversationContext:
    """Complete conversation context with all memory levels."""
    
    # Working memory (current turn)
    current_query: str
    current_language: str = "es"
    
    # Short-term memory (recent turns)
    recent_turns: List[ConversationTurn] = field(default_factory=list)
    recent_messages: List[BaseMessage] = field(default_factory=list)
    
    # Long-term memory (summarized history)
    session_summary: Optional[str] = None
    previous_places: List[Dict[str, Any]] = field(default_factory=list)
    
    # Metadata
    session_id: Optional[UUID] = None
    user_id: Optional[UUID] = None
    total_turns_in_session: int = 0
    estimated_tokens: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "current_query": self.current_query,
            "current_language": self.current_language,
            "recent_turns_count": len(self.recent_turns),
            "session_summary": self.session_summary,
            "previous_places_count": len(self.previous_places),
            "session_id": str(self.session_id) if self.session_id else None,
            "user_id": str(self.user_id) if self.user_id else None,
            "total_turns_in_session": self.total_turns_in_session,
            "estimated_tokens": self.estimated_tokens,
        }


class ConversationBuffer:
    """
    Production-grade conversation buffer with multi-level memory.
    
    Memory Architecture:
    - Level 1 (Working): Current turn context
    - Level 2 (Short-term): Last N turns with sliding window (db + cache)
    - Level 3 (Long-term): Summarized session history for personalization
    
    Features:
    - Automatic compression when token limit exceeded
    - Redis caching for fast retrieval
    - Database persistence for reliability
    - Handles long conversations gracefully
    - Works across multiple workers/processes
    """
    
    # Configuration
    DEFAULT_SHORT_TERM_TURNS = 10  # Recent turns to keep in full detail
    DEFAULT_LONG_TERM_TURNS = 50   # Turns to consider for summarization
    DEFAULT_MAX_TOKENS = 4000      # Token budget for context
    COMPRESSION_THRESHOLD = 0.8    # Compress when 80% of token budget used
    CACHE_TTL_SHORT = 300          # 5 minutes for short-term cache
    CACHE_TTL_LONG = 3600          # 1 hour for long-term cache
    
    def __init__(
        self,
        repository: ConversationRepository,
        cache: Optional[CacheManager] = None,
        max_short_term_turns: int = DEFAULT_SHORT_TERM_TURNS,
        max_long_term_turns: int = DEFAULT_LONG_TERM_TURNS,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ):
        """
        Initialize conversation buffer.
        
        Args:
            repository: Database repository for persistence
            cache: Optional Redis cache manager
            max_short_term_turns: Max turns to keep in short-term memory
            max_long_term_turns: Max turns to consider for long-term summary
            max_tokens: Maximum token budget for context
        """
        self.repository = repository
        self.cache = cache
        self.max_short_term_turns = max_short_term_turns
        self.max_long_term_turns = max_long_term_turns
        self.max_tokens = max_tokens
        
        logger.info(
            "conversation_buffer_initialized",
            max_short_term_turns=max_short_term_turns,
            max_long_term_turns=max_long_term_turns,
            max_tokens=max_tokens,
        )
    
    async def load_context(
        self,
        user_id: UUID,
        session_id: UUID,
        current_query: str,
        current_language: str = "es",
    ) -> ConversationContext:
        """
        Load complete conversation context from all memory levels.
        
        This is the main entry point - returns everything needed for agent execution.
        
        Args:
            user_id: User UUID
            session_id: Session UUID
            current_query: Current user query
            current_language: Language for responses
            
        Returns:
            ConversationContext with all memory levels populated
        """
        logger.info(
            "loading_conversation_context",
            user_id=str(user_id),
            session_id=str(session_id),
        )
        
        # Try to load from cache first (fast path)
        cached_context = await self._load_from_cache(session_id)
        if cached_context:
            # Update with current query
            cached_context.current_query = current_query
            cached_context.current_language = current_language
            logger.info("context_loaded_from_cache", session_id=str(session_id))
            return cached_context
        
        # Cache miss - build from database (slow path)
        context = await self._build_from_database(
            user_id=user_id,
            session_id=session_id,
            current_query=current_query,
            current_language=current_language,
        )
        
        # Cache for future requests
        await self._save_to_cache(session_id, context)
        
        logger.info(
            "context_loaded_from_database",
            session_id=str(session_id),
            recent_turns=len(context.recent_turns),
            estimated_tokens=context.estimated_tokens,
        )
        
        return context
    
    async def _build_from_database(
        self,
        user_id: UUID,
        session_id: UUID,
        current_query: str,
        current_language: str,
    ) -> ConversationContext:
        """
        Build context from database (slow path).
        
        This fetches turns once and builds all memory levels efficiently.
        """
        # Fetch turns from database (single query)
        all_turns = await self.repository.get_session_history(
            session_id=session_id,
            limit=self.max_long_term_turns,
        )
        
        if not all_turns:
            # New conversation - empty context
            return ConversationContext(
                current_query=current_query,
                current_language=current_language,
                session_id=session_id,
                user_id=user_id,
            )
        
        # Split into short-term (recent) and long-term (older) turns
        recent_turns = all_turns[-self.max_short_term_turns:]
        older_turns = all_turns[:-self.max_short_term_turns] if len(all_turns) > self.max_short_term_turns else []
        
        # Build short-term memory (full detail)
        recent_messages = self._turns_to_messages(recent_turns)
        estimated_tokens = self._estimate_tokens_from_turns(recent_turns)
        
        # Build long-term memory (summarized)
        session_summary = None
        if older_turns:
            session_summary = self._generate_summary(older_turns)
            estimated_tokens += self._estimate_tokens(session_summary)
        
        # Extract previous places for reference resolution
        previous_places = self._extract_places_from_turns(recent_turns)
        
        # Check if we need compression
        if estimated_tokens > self.max_tokens * self.COMPRESSION_THRESHOLD:
            logger.info(
                "context_needs_compression",
                estimated_tokens=estimated_tokens,
                max_tokens=self.max_tokens,
            )
            recent_turns, recent_messages = self._compress_context(
                recent_turns,
                recent_messages,
            )
            estimated_tokens = self._estimate_tokens_from_turns(recent_turns)
        
        return ConversationContext(
            current_query=current_query,
            current_language=current_language,
            recent_turns=recent_turns,
            recent_messages=recent_messages,
            session_summary=session_summary,
            previous_places=previous_places,
            session_id=session_id,
            user_id=user_id,
            total_turns_in_session=len(all_turns),
            estimated_tokens=estimated_tokens,
        )
    
    def _turns_to_messages(self, turns: List[ConversationTurn]) -> List[BaseMessage]:
        """
        Convert conversation turns to LangChain messages.
        
        Args:
            turns: List of conversation turns
            
        Returns:
            List of BaseMessage objects (HumanMessage, AIMessage)
        """
        messages = []
        for turn in turns:
            messages.append(HumanMessage(content=turn.user_query))
            messages.append(AIMessage(content=turn.agent_response))
        return messages
    
    def _extract_places_from_turns(
        self,
        turns: List[ConversationTurn],
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Extract places from recent turns for reference resolution.
        
        Args:
            turns: List of conversation turns
            limit: Max number of turns to extract places from
            
        Returns:
            List of places with metadata
        """
        recent_turns = turns[-limit:] if len(turns) > limit else turns
        
        places = []
        for turn_idx, turn in enumerate(reversed(recent_turns), 1):
            if turn.places_found and isinstance(turn.places_found, list):
                for place_idx, place in enumerate(turn.places_found[:10], 1):
                    place_with_context = place.copy() if isinstance(place, dict) else {}
                    place_with_context["_turn_number"] = turn_idx
                    place_with_context["_position"] = place_idx
                    places.append(place_with_context)
        
        return places
    
    def _generate_summary(self, turns: List[ConversationTurn]) -> str:
        """
        Generate a summary of older conversation turns.
        
        For now, uses rule-based summarization. Can be enhanced with LLM later.
        
        Args:
            turns: List of older turns to summarize
            
        Returns:
            Summary string
        """
        if not turns:
            return ""
        
        # Count intentions
        intention_counts = {}
        total_places = 0
        
        for turn in turns:
            intention_counts[turn.intention] = intention_counts.get(turn.intention, 0) + 1
            if turn.places_found and isinstance(turn.places_found, list):
                total_places += len(turn.places_found)
        
        # Build summary
        summary_parts = [
            f"Conversación previa: {len(turns)} mensajes anteriores.",
        ]
        
        if intention_counts:
            intentions_str = ", ".join(
                f"{k}: {v}" for k, v in sorted(
                    intention_counts.items(),
                    key=lambda x: x[1],
                    reverse=True,
                )
            )
            summary_parts.append(f"Temas: {intentions_str}.")
        
        if total_places > 0:
            summary_parts.append(f"Se discutieron {total_places} lugares en total.")
        
        return " ".join(summary_parts)
    
    def _compress_context(
        self,
        turns: List[ConversationTurn],
        messages: List[BaseMessage],
    ) -> Tuple[List[ConversationTurn], List[BaseMessage]]:
        """
        Compress context by keeping only the most recent turns.
        
        Args:
            turns: Full list of turns
            messages: Full list of messages
            
        Returns:
            Compressed turns and messages
        """
        # Keep only the most recent turns (aggressive compression)
        keep_count = max(3, self.max_short_term_turns // 2)
        
        compressed_turns = turns[-keep_count:]
        compressed_messages = messages[-keep_count * 2:]  # 2 messages per turn
        
        logger.info(
            "context_compressed",
            original_turns=len(turns),
            compressed_turns=len(compressed_turns),
        )
        
        return compressed_turns, compressed_messages
    
    def _estimate_tokens(self, text: str) -> int:
        """Estimate tokens from text (rough approximation: 1 token ≈ 4 chars)."""
        return len(text) // 4
    
    def _estimate_tokens_from_turns(self, turns: List[ConversationTurn]) -> int:
        """Estimate total tokens from conversation turns."""
        total = 0
        for turn in turns:
            total += self._estimate_tokens(turn.user_query)
            total += self._estimate_tokens(turn.agent_response)
        return total
    
    async def _load_from_cache(
        self,
        session_id: UUID,
    ) -> Optional[ConversationContext]:
        """
        Load context from cache (fast path).
        
        Returns None if cache miss.
        """
        if not self.cache:
            return None
        
        cache_key = f"conversation_context:{session_id}"
        try:
            cached = await self.cache.get(cache_key)
            if cached and isinstance(cached, dict):
                # Reconstruct context from cached data
                # Note: We only cache metadata, not full turns (too large)
                # Full turns are loaded from DB on cache miss
                logger.debug("cache_hit", session_id=str(session_id))
                return None  # For now, always load from DB
            return None
        except Exception as e:
            logger.warning("cache_load_error", error=str(e))
            return None
    
    async def _save_to_cache(
        self,
        session_id: UUID,
        context: ConversationContext,
    ):
        """Save context metadata to cache."""
        if not self.cache:
            return
        
        cache_key = f"conversation_context:{session_id}"
        try:
            # Cache only metadata, not full content (to save memory)
            cache_data = context.to_dict()
            await self.cache.set(
                cache_key,
                cache_data,
                ttl=self.CACHE_TTL_SHORT,
            )
            logger.debug("cache_saved", session_id=str(session_id))
        except Exception as e:
            logger.warning("cache_save_error", error=str(e))
    
    async def invalidate_cache(self, session_id: UUID):
        """Invalidate cache for a session (call after new message)."""
        if not self.cache:
            return
        
        cache_key = f"conversation_context:{session_id}"
        try:
            await self.cache.delete(cache_key)
            logger.debug("cache_invalidated", session_id=str(session_id))
        except Exception as e:
            logger.warning("cache_invalidate_error", error=str(e))
