"""
Context builder for constructing optimized prompts with conversation memory.

This takes the ConversationContext and builds the optimal prompt format for LLMs,
handling different memory levels, place references, and plan state.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from uuid import UUID

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

from src.agents.conversation_buffer import ConversationContext
from src.utils.logger import get_logger

logger = get_logger("context_builder")


class ContextBuilder:
    """
    Builds optimized context for agent prompts from conversation memory.
    
    Responsibilities:
    - Format conversation history for LLM consumption
    - Inject place references for disambiguation
    - Handle plan state tracking across turns
    - Manage token budgets efficiently
    - Provide both string and message-based formats
    """
    
    def __init__(self, max_context_tokens: int = 4000):
        """
        Initialize context builder.
        
        Args:
            max_context_tokens: Maximum tokens to use for context
        """
        self.max_context_tokens = max_context_tokens
    
    def build_messages(
        self,
        context: ConversationContext,
        system_prompt: str,
    ) -> List[BaseMessage]:
        """
        Build message list for agent execution (LangChain format).
        
        This is the preferred format for ReAct agents and LangGraph.
        
        Args:
            context: Conversation context with all memory levels
            system_prompt: System prompt template
            
        Returns:
            List of BaseMessage objects ready for agent
        """
        messages = []
        
        # 1. System message with enhanced context
        enhanced_system = self._enhance_system_prompt(system_prompt, context)
        messages.append(SystemMessage(content=enhanced_system))
        
        # 2. Long-term memory (if exists) as system context
        if context.session_summary:
            messages.append(
                SystemMessage(
                    content=f"## 📚 Contexto de Sesión\n{context.session_summary}"
                )
            )
        
        # 3. Short-term memory (recent conversation)
        if context.recent_messages:
            # Add recent conversation messages
            messages.extend(context.recent_messages)
        
        # 4. Place references (if any) as system context
        if context.previous_places:
            places_context = self._format_place_references(context.previous_places)
            messages.append(
                SystemMessage(
                    content=f"## 📍 Lugares Mencionados Recientemente\n{places_context}"
                )
            )
        
        # 5. Current query
        messages.append(HumanMessage(content=context.current_query))
        
        logger.debug(
            "messages_built",
            total_messages=len(messages),
            session_id=str(context.session_id) if context.session_id else None,
        )
        
        return messages
    
    def build_string_context(
        self,
        context: ConversationContext,
        include_metadata: bool = True,
    ) -> str:
        """
        Build string-based context (for prompts that don't use message format).
        
        Args:
            context: Conversation context
            include_metadata: Include session metadata
            
        Returns:
            Formatted context string
        """
        parts = []
        
        # Metadata
        if include_metadata and context.total_turns_in_session > 0:
            parts.append(
                f"📊 Sesión: {context.total_turns_in_session} mensajes previos "
                f"({context.estimated_tokens} tokens)"
            )
            parts.append("")
        
        # Long-term summary
        if context.session_summary:
            parts.append("## 📚 Contexto de Sesión")
            parts.append(context.session_summary)
            parts.append("")
        
        # Recent conversation
        if context.recent_turns:
            parts.append("## 💬 Conversación Reciente")
            for turn in context.recent_turns:
                parts.append(f"**Usuario**: {turn.user_query}")
                parts.append(f"**Asistente**: {turn.agent_response}")
                parts.append("")
        
        # Place references
        if context.previous_places:
            parts.append("## 📍 Lugares Mencionados")
            parts.append(self._format_place_references(context.previous_places))
            parts.append("")
        
        return "\n".join(parts)
    
    def build_agent_context_dict(
        self,
        context: ConversationContext,
        validated_context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Build context dictionary for agent execution.
        
        This is the format used by supervisor and specialized agents.
        
        Args:
            context: Conversation context
            validated_context: Optional validated user context (location, preferences, etc.)
            
        Returns:
            Dictionary with all context needed by agents
        """
        agent_context = {
            # Identity
            "user_id": str(context.user_id) if context.user_id else None,
            "session_id": str(context.session_id) if context.session_id else None,
            
            # Current query
            "current_query": context.current_query,
            "language": context.current_language,
            
            # Memory (messages format for agents)
            "history_messages": context.recent_messages,
            "conversation_history": self.build_string_context(context, include_metadata=False),
            
            # Place context
            "previous_places": context.previous_places,
            
            # Session metadata
            "total_turns": context.total_turns_in_session,
            "session_summary": context.session_summary,
            
            # Token budget info
            "estimated_tokens": context.estimated_tokens,
            "tokens_remaining": max(0, self.max_context_tokens - context.estimated_tokens),
        }
        
        # Merge with validated context if provided
        if validated_context:
            agent_context["validated_context"] = validated_context
        
        return agent_context
    
    def extract_plan_state(
        self,
        context: ConversationContext,
    ) -> Dict[str, Any]:
        """
        Extract plan-specific state from conversation history.
        
        This replaces the old PlanMemoryManager by extracting plan state
        from conversation metadata stored in the database.
        
        Args:
            context: Conversation context
            
        Returns:
            Dictionary with plan state (duration, num_people, cities, etc.)
        """
        plan_state = {
            "duration": None,
            "num_people": None,
            "cities": [],
            "place_types": [],
            "vibe": None,
            "budget": None,
            "transport": None,
            "missing_fields": [],
        }
        
        # Extract plan info from recent turns' metadata
        for turn in context.recent_turns:
            if turn.intention == "PLAN" and turn.extra_metadata:
                metadata = turn.extra_metadata
                
                # Extract fields from metadata
                if metadata.get("duration"):
                    plan_state["duration"] = metadata["duration"]
                if metadata.get("num_people"):
                    plan_state["num_people"] = metadata["num_people"]
                if metadata.get("cities"):
                    plan_state["cities"] = metadata["cities"]
                if metadata.get("place_types"):
                    plan_state["place_types"] = metadata["place_types"]
                if metadata.get("vibe"):
                    plan_state["vibe"] = metadata["vibe"]
                if metadata.get("budget"):
                    plan_state["budget"] = metadata["budget"]
                if metadata.get("transport"):
                    plan_state["transport"] = metadata["transport"]
        
        # Determine missing required fields
        required_fields = ["duration", "num_people", "cities", "place_types", "vibe"]
        plan_state["missing_fields"] = [
            field for field in required_fields
            if not plan_state[field]
        ]
        
        plan_state["is_complete"] = len(plan_state["missing_fields"]) == 0
        
        logger.debug(
            "plan_state_extracted",
            is_complete=plan_state["is_complete"],
            missing_fields=plan_state["missing_fields"],
        )
        
        return plan_state
    
    def _enhance_system_prompt(
        self,
        base_prompt: str,
        context: ConversationContext,
    ) -> str:
        """
        Enhance system prompt with context-aware information.
        
        Args:
            base_prompt: Base system prompt
            context: Conversation context
            
        Returns:
            Enhanced prompt with context
        """
        enhancements = []
        
        # Add session context if this is a continuing conversation
        if context.total_turns_in_session > 0:
            enhancements.append(
                f"\n## 🔄 Información de Sesión\n"
                f"Esta es una conversación continua con {context.total_turns_in_session} mensajes previos. "
                f"Usa el contexto de la conversación para dar respuestas coherentes y personalizadas."
            )
        
        # Add place reference instructions if places were discussed
        if context.previous_places:
            enhancements.append(
                f"\n## 📍 Referencias a Lugares\n"
                f"El usuario puede referirse a lugares mencionados anteriormente "
                f"(ej: 'el segundo', 'el que dijiste antes', 'ese bar'). "
                f"Usa la sección '📍 Lugares Mencionados Recientemente' para resolver estas referencias."
            )
        
        if enhancements:
            return base_prompt + "\n" + "\n".join(enhancements)
        
        return base_prompt
    
    def _format_place_references(
        self,
        places: List[Dict[str, Any]],
        max_places: int = 10,
    ) -> str:
        """
        Format place references for context injection.
        
        Args:
            places: List of places with metadata
            max_places: Maximum places to include
            
        Returns:
            Formatted string with place references
        """
        if not places:
            return "No hay lugares mencionados recientemente."
        
        lines = []
        for i, place in enumerate(places[:max_places], 1):
            name = place.get("name", "Desconocido")
            turn = place.get("_turn_number", "?")
            position = place.get("_position", "?")
            
            # Include key details if available
            details = []
            if place.get("rating"):
                details.append(f"⭐ {place['rating']}")
            if place.get("price_level"):
                details.append(f"💰 {'€' * place['price_level']}")
            if place.get("category"):
                details.append(f"📁 {place['category']}")
            
            details_str = " | ".join(details) if details else ""
            lines.append(
                f"{i}. **{name}** (turno -{turn}, posición {position}) {details_str}"
            )
        
        if len(places) > max_places:
            lines.append(f"... y {len(places) - max_places} lugares más")
        
        return "\n".join(lines)


class PlanContextExtractor:
    """
    Extracts and manages plan-specific context from conversation.
    
    This replaces PlanMemoryManager with a database-backed approach.
    """
    
    # Required fields for plan creation
    REQUIRED_FIELDS = ["duration", "num_people", "cities", "place_types", "vibe"]
    
    # Optional fields
    OPTIONAL_FIELDS = ["budget", "transport", "dietary_restrictions", "accessibility"]
    
    @staticmethod
    def extract_from_query(query: str, language: str = "es") -> Dict[str, Any]:
        """
        Extract plan parameters from user query using heuristics.
        
        This is a simple rule-based extraction. Can be enhanced with NER/LLM later.
        
        Args:
            query: User query
            language: Query language
            
        Returns:
            Dictionary with extracted plan parameters
        """
        extracted = {}
        query_lower = query.lower()
        
        # Extract number of people
        import re
        people_patterns = [
            r'(\d+)\s*personas?',
            r'para\s*(\d+)',
            r'somos\s*(\d+)',
            r'(\d+)\s*amigos?',
        ]
        for pattern in people_patterns:
            match = re.search(pattern, query_lower)
            if match:
                extracted["num_people"] = int(match.group(1))
                break
        
        # Extract duration keywords
        duration_keywords = {
            "mañana": "morning",
            "tarde": "afternoon",
            "noche": "evening",
            "fin de semana": "weekend",
            "día completo": "full_day",
            "2 horas": "2_hours",
            "medio día": "half_day",
        }
        for keyword, value in duration_keywords.items():
            if keyword in query_lower:
                extracted["duration"] = value
                break
        
        # Extract cities (simple keyword matching)
        city_keywords = ["zaragoza", "madrid", "barcelona", "valencia"]
        for city in city_keywords:
            if city in query_lower:
                extracted["cities"] = [city.title()]
                break
        
        # Extract place types
        place_type_keywords = {
            "bar": "bars",
            "bares": "bars",
            "restaurante": "restaurants",
            "restaurantes": "restaurants",
            "museo": "museums",
            "museos": "museums",
            "parque": "parks",
            "parques": "parks",
            "café": "cafes",
            "cafés": "cafes",
        }
        place_types = []
        for keyword, place_type in place_type_keywords.items():
            if keyword in query_lower:
                place_types.append(place_type)
        if place_types:
            extracted["place_types"] = list(set(place_types))  # Deduplicate
        
        # Extract vibe
        vibe_keywords = {
            "romántico": "romantic",
            "romántica": "romantic",
            "tranquilo": "chill",
            "tranquila": "chill",
            "divertido": "party",
            "fiesta": "party",
            "aventura": "adventure",
            "familia": "family",
        }
        for keyword, vibe in vibe_keywords.items():
            if keyword in query_lower:
                extracted["vibe"] = vibe
                break
        
        logger.debug("plan_extraction_attempted", extracted=extracted, query_length=len(query))
        
        return extracted
    
    @staticmethod
    def merge_plan_state(
        existing: Dict[str, Any],
        new: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Merge new plan parameters with existing state.
        
        Args:
            existing: Existing plan state
            new: Newly extracted parameters
            
        Returns:
            Merged plan state
        """
        merged = existing.copy()
        
        for key, value in new.items():
            if key in ["cities", "place_types"]:
                # Merge lists
                existing_list = merged.get(key, [])
                if isinstance(existing_list, list) and isinstance(value, list):
                    merged[key] = list(set(existing_list + value))
                else:
                    merged[key] = value
            else:
                # Override scalar values (new info takes precedence)
                if value:
                    merged[key] = value
        
        return merged
    
    @staticmethod
    def is_plan_ready(plan_state: Dict[str, Any]) -> tuple[bool, List[str]]:
        """
        Check if plan has all required fields.
        
        Args:
            plan_state: Plan state dictionary
            
        Returns:
            Tuple of (is_ready, missing_fields)
        """
        missing = []
        for field in PlanContextExtractor.REQUIRED_FIELDS:
            value = plan_state.get(field)
            if not value or (isinstance(value, list) and len(value) == 0):
                missing.append(field)
        
        return len(missing) == 0, missing
    
    @staticmethod
    def format_missing_fields_prompt(missing: List[str], language: str = "es") -> str:
        """
        Generate a friendly prompt to ask for missing fields.
        
        Args:
            missing: List of missing field names
            language: Response language
            
        Returns:
            User-friendly question
        """
        if not missing:
            return ""
        
        # Spanish translations
        field_names_es = {
            "duration": "duración del plan",
            "num_people": "número de personas",
            "cities": "ciudad o ciudades",
            "place_types": "tipo de lugares (bares, restaurantes, etc.)",
            "vibe": "ambiente que buscas (romántico, aventura, etc.)",
        }
        
        if len(missing) == 1:
            field = field_names_es.get(missing[0], missing[0])
            return f"Para ayudarte mejor, ¿podrías decirme {field}?"
        
        fields = [field_names_es.get(f, f) for f in missing]
        fields_str = ", ".join(fields[:-1]) + f" y {fields[-1]}"
        return f"Para crear el plan perfecto, necesito saber: {fields_str}."
