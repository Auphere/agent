"""
Base class for specialized agents with common functionality.

This reduces code duplication and ensures consistent behavior across:
- SearchAgent
- RecommendAgent
- PlanAndExecuteAgent

Features:
- Common initialization pattern
- Shared tool execution logic
- Consistent response handling
- Built-in caching support
- Proper tool binding with tool_choice
"""

from __future__ import annotations

import asyncio
import operator
from abc import ABC, abstractmethod
from time import perf_counter
from typing import Any, Dict, List, Optional, TypedDict, Annotated, Sequence, Tuple, Union

from langchain_core.messages import BaseMessage, AIMessage, HumanMessage, SystemMessage
from langchain_core.tools import BaseTool
from langchain_openai import ChatOpenAI

from src.agents.utils.place_extractor import extract_places_from_messages
from src.agents.utils.place_saver import save_places_to_db
from src.agents.utils.text_cleaner import clean_response_text
from src.agents.utils.response_parser import extract_final_answer
from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger
from src.utils.cache_manager import get_cache_manager
from src.utils.metrics import get_metrics_collector, timed
from src.utils.language_handler import get_language_handler, LanguageHandler
from src.utils.response_validator import get_response_validator, ResponseValidator

def _is_outside_coverage_tool_result(tool_result: Any) -> bool:
    try:
        return isinstance(tool_result, dict) and tool_result.get("error") == "OUTSIDE_COVERAGE"
    except Exception:
        return False


async def _render_outside_coverage_message(
    *,
    llm: ChatOpenAI,
    settings: Settings,
    query: str,
    language: str,
    tool_result: Dict[str, Any],
) -> str:
    """Ask the LLM to craft a friendly message about MVP coverage limitations."""
    coverage = tool_result.get("coverage") if isinstance(tool_result, dict) else {}
    country_name = (coverage or {}).get("country_name", "")
    country_code = (coverage or {}).get("country_code", "")
    allowed = (coverage or {}).get("allowed_countries", settings.coverage_countries_list)
    policy_note = getattr(settings, "coverage_policy_note", "")

    prompt = f"""You are Auphere, a helpful assistant.

The user requested something outside our current MVP coverage.

Policy (non user-facing): {policy_note}
Allowed countries (ISO): {allowed}
Detected country: {country_name} ({country_code})

User language: {language}
User query: {query}

Write a short, friendly response in the user's language.
Constraints:
- Do NOT mention internal tools, errors, logs, or policy text verbatim.
- Explain we currently have limited coverage during MVP.
- Ask the user to choose a city within the supported coverage to continue.
- Keep it concise (1-3 sentences)."""

    msg = await llm.ainvoke([SystemMessage(content=prompt)])
    return clean_response_text(getattr(msg, "content", str(msg)))


# ============================================================================
# Reference resolution helpers (e.g., "el segundo", "the first one")
# ============================================================================

_ORDINAL_TO_INDEX: Dict[str, int] = {
    # Spanish
    "primero": 1,
    "primer": 1,
    "primera": 1,
    "segundo": 2,
    "segunda": 2,
    "tercero": 3,
    "tercera": 3,
    "cuarto": 4,
    "cuarta": 4,
    "quinto": 5,
    "quinta": 5,
    # English
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
}


def _extract_reference_position(query: str) -> Optional[int]:
    q = query.lower().strip()
    for word, idx in _ORDINAL_TO_INDEX.items():
        if f" {word}" in f" {q}":
            return idx

    # Minimal numeric support only when explicitly phrased as "del 2" / "the 2nd"
    import re

    m = re.search(r"\bdel\s+(\d+)\b", q)
    if m:
        try:
            n = int(m.group(1))
            return n if 1 <= n <= 10 else None
        except Exception:
            return None

    m = re.search(r"\bthe\s+(\d+)(?:st|nd|rd|th)?\b", q)
    if m:
        try:
            n = int(m.group(1))
            return n if 1 <= n <= 10 else None
        except Exception:
            return None

    return None


def _resolve_place_id_from_previous_places(previous_places: List[Dict[str, Any]], position: int) -> Optional[str]:
    """
    Select the place referenced by `_position_in_turn` from the most recent turn,
    returning an identifier that `auphere-places` can resolve (google place_id preferred).
    """
    if not previous_places:
        return None

    def _turn(p: Dict[str, Any]) -> int:
        try:
            return int(p.get("_turn_number") or 0)
        except Exception:
            return 0

    most_recent_turn = max((_turn(p) for p in previous_places), default=0)
    candidates = [p for p in previous_places if _turn(p) == most_recent_turn]
    if not candidates:
        candidates = previous_places

    target = None
    # Prefer explicit position metadata (most reliable)
    for p in candidates:
        try:
            if int(p.get("_position_in_turn") or -1) == position:
                target = p
                break
        except Exception:
            continue

    # Fallback: assume `candidates` are already ordered as shown to the user
    # (this covers cases where _position_in_turn was not injected).
    if not target:
        idx = position - 1
        if 0 <= idx < len(candidates):
            target = candidates[idx]

    if not target:
        return None

    # Preferred: google place id
    return (
        target.get("place_id")
        or target.get("google_place_id")
        or target.get("id")
        or target.get("db_id")
    )

# ============================================================================
# Shared State Types with proper reducers
# ============================================================================

class AgentState(TypedDict, total=False):
    """
    Base state schema for all specialized agents.
    
    Uses Annotated with operator.add for proper message accumulation
    following LangGraph best practices.
    """
    # Input (immutable)
    input: str
    language: str
    context: Dict[str, Any]
    
    # Messages with proper reducer for accumulation
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # Output
    response_text: str
    places: List[Dict[str, Any]]
    
    # Metadata
    agent_type: str
    model_used: str
    tool_calls: int
    reasoning_steps: int


# ============================================================================
# Base Agent Class
# ============================================================================

class BaseSpecializedAgent(ABC):
    """
    Abstract base class for specialized agents.
    
    Provides:
    - Common LLM initialization with configurable timeouts
    - Tool binding with tool_choice support
    - Consistent logging
    - Cache integration
    - Place extraction and saving
    - Response cleaning
    - Retry logic for transient failures
    
    Subclasses must implement:
    - get_tools(): Return list of tools for this agent
    - get_system_prompt(): Return system prompt for this agent
    - agent_type: Property returning agent type name
    
    Timeout Configuration:
    - timeout can be int/float (single value) or tuple (connect, read)
    - Tuple format is recommended: (5.0, 60.0) = 5s connect, 60s read
    """
    
    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        temperature: float = 0.5,
        timeout: Union[float, Tuple[float, float]] = None,
        max_retries: int = None,
        settings: Settings | None = None,
    ) -> None:
        """
        Initialize base agent.
        
        Args:
            model_name: OpenAI model to use
            temperature: LLM temperature
            timeout: Request timeout - can be:
                     - float: single timeout for all operations
                     - tuple: (connection_timeout, read_timeout)
                     - None: use settings defaults
            max_retries: Max retry attempts (None = use settings default)
            settings: Application settings
        """
        self.settings = settings or get_settings()
        self.logger = get_logger(f"{self.agent_type}-agent", settings=self.settings)
        
        # Configure timeout from settings if not provided
        if timeout is None:
            timeout = (
                self.settings.llm_connection_timeout,
                self.settings.llm_read_timeout_standard
            )
        
        # Configure retries from settings if not provided
        if max_retries is None:
            max_retries = self.settings.llm_max_retries
        
        # Store timeout config for logging/debugging
        self._timeout_config = timeout
        self._max_retries = max_retries
        
        # Initialize LLM with improved configuration
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            api_key=self.settings.openai_api_key,
            timeout=timeout,  # Now supports tuple (connect, read)
            max_retries=max_retries,
        )
        
        # Get tools for this agent type
        self.tools = self.get_tools()
        
        # Create LLM with tools bound
        self.llm_with_tools = self.llm.bind_tools(self.tools)
        
        self.logger.info(
            f"{self.agent_type}-agent-initialized",
            model=model_name,
            tools_count=len(self.tools),
            timeout=str(timeout),
            max_retries=max_retries,
        )
    
    @property
    @abstractmethod
    def agent_type(self) -> str:
        """Return the agent type identifier."""
        pass
    
    @abstractmethod
    def get_tools(self) -> List[BaseTool]:
        """Return list of tools for this agent."""
        pass
    
    @abstractmethod
    def get_system_prompt(self, context: Dict[str, Any], language: str) -> str:
        """
        Return system prompt for this agent.
        
        Args:
            context: Request context
            language: Response language
            
        Returns:
            System prompt string
        """
        pass
    
    def should_force_tool(self, query: str) -> bool:
        """
        Determine if tool usage should be forced for this query.
        
        Override in subclasses for agent-specific logic.
        
        Args:
            query: User query
            
        Returns:
            True if tool usage should be forced
        """
        query_lower = query.lower()
        
        # Common indicators that require tool usage
        search_indicators = [
            "busca", "encuentra", "muestra", "dame",
            "search", "find", "show", "give me",
            "recomienda", "recommend", "suggest",
            "quiero", "necesito", "looking for",
        ]
        
        place_indicators = [
            "restaurante", "bar", "cafe", "café", "club",
            "lugar", "sitio", "place", "spot",
            "restaurant", "hotel", "museo", "museum",
        ]
        
        return (
            any(ind in query_lower for ind in search_indicators) or
            any(ind in query_lower for ind in place_indicators)
        )
    
    def get_primary_tool_name(self) -> Optional[str]:
        """
        Return the primary tool name for forced tool_choice.
        
        Override in subclasses to specify which tool to force.
        
        Returns:
            Tool name or None for auto selection
        """
        return "places_search_tool"
    
    async def run(
        self,
        query: str,
        language: str = "es",
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Execute the agent with comprehensive error handling and metrics.
        
        Args:
            query: User query
            language: Response language (auto-detected if not specified)
            context: Additional context
            
        Returns:
            Dict with response_text, places, and metadata
        """
        context = context or {}
        start_time = perf_counter()
        
        # Language detection and standardization (English-first processing)
        lang_handler = get_language_handler()
        detected_lang, response_lang, search_lang, unsupported_msg = lang_handler.process_input(query)
        
        # Override language with detected if auto-detection preferred
        # But respect explicit language parameter if different from default
        if language == "es" or language == "en":
            # Use detected language for better UX
            language = response_lang
        
        # Log language detection
        self.logger.info(
            "language-processing",
            detected=detected_lang,
            response_lang=response_lang,
            search_lang=search_lang,
            is_supported=lang_handler.is_supported(detected_lang),
        )
        
        # Initialize metrics
        metrics_collector = get_metrics_collector()
        agent_metrics = metrics_collector.start_agent_execution(
            agent_type=self.agent_type,
            query=query,
        )
        agent_metrics.model_used = self.llm.model_name
        
        self.logger.info(
            f"{self.agent_type}-agent-starting",
            query=query,
            language=language,
            timeout=str(self._timeout_config),
        )
        
        # Fast-path: resolve references like "el segundo" using previous_places + places_get_place_tool.
        # This avoids forcing places_search_tool and removes an unnecessary extra search round-trip.
        previous_places = context.get("previous_places", []) if isinstance(context, dict) else []
        position = _extract_reference_position(query)
        if position and previous_places:
            place_identifier = _resolve_place_id_from_previous_places(previous_places, position)
            if place_identifier:
                self.logger.info(
                    "reference-resolved",
                    query=query,
                    position=position,
                    resolved_id=place_identifier,
                    previous_places_count=len(previous_places),
                )
                tool = next((t for t in self.tools if t.name == "places_get_place_tool"), None)
                if tool:
                    try:
                        tool_start = perf_counter()
                        tool_result = await asyncio.wait_for(
                            tool.ainvoke({"place_id": place_identifier}),
                            timeout=self.settings.tool_timeout,
                        )
                        tool_duration = perf_counter() - tool_start
                        self.logger.debug(
                            "tool-executed",
                            tool="places_get_place_tool",
                            duration_ms=int(tool_duration * 1000),
                        )

                        place = None
                        if isinstance(tool_result, dict) and tool_result.get("success") and tool_result.get("place"):
                            place = tool_result["place"]

                        if place:
                            # Keep response text short; cards will show full detail.
                            name = place.get("name") or "Este lugar"
                            rating = place.get("rating")
                            count = place.get("user_ratings_total")
                            price = place.get("price_level")

                            if language.startswith("es"):
                                parts = [f"Aquí tienes más info de **{name}**."]
                                if rating:
                                    suffix = f"⭐ {rating}/5"
                                    if count:
                                        suffix += f" ({count} reseñas)"
                                    parts.append(suffix + ".")
                                if price is not None:
                                    parts.append(f"Precio (Google): {price}/4.")
                                parts.append("¿Quieres ver fotos/reseñas o que lo agregue a un plan?")
                                response_text = " ".join(parts)
                            else:
                                parts = [f"Here’s more info about **{name}**."]
                                if rating:
                                    suffix = f"⭐ {rating}/5"
                                    if count:
                                        suffix += f" ({count} reviews)"
                                    parts.append(suffix + ".")
                                if price is not None:
                                    parts.append(f"Price level (Google): {price}/4.")
                                parts.append("Want photos/reviews, or should I add it to a plan?")
                                response_text = " ".join(parts)

                            # Save/update in DB (best-effort)
                            places = [place]
                            try:
                                places = await save_places_to_db(places, self.settings)
                                self.logger.info("places-saved-to-db", count=len(places))
                            except Exception as exc:
                                self.logger.error("failed-to-save-places", error=str(exc))

                            total_duration = perf_counter() - start_time
                            agent_metrics.tool_calls = 1
                            agent_metrics.places_found = len(places)
                            metrics_collector.end_agent_execution(agent_metrics, success=True)

                            return {
                                "response_text": clean_response_text(response_text),
                                "places": places,
                                "tool_calls": 1,
                                "reasoning_steps": 1,
                                "agent_type": self.agent_type,
                                "model_used": self.llm.model_name,
                                "duration_ms": int(total_duration * 1000),
                            }
                    except Exception as exc:
                        # If anything goes wrong, fall back to normal LLM flow.
                        self.logger.warning("reference-fast-path-failed", error=str(exc))
            else:
                # We detected an ordinal reference but couldn't map it to an id.
                # This is usually due to missing `_position_in_turn` / ordering in previous_places.
                self.logger.warning(
                    "reference-detected-but-unresolved",
                    query=query,
                    position=position,
                    previous_places_count=len(previous_places),
                    sample_keys=list(previous_places[0].keys()) if previous_places else [],
                )

        # Build messages
        system_prompt = self.get_system_prompt(context, language)
        messages: List[BaseMessage] = [SystemMessage(content=system_prompt)]
        
        # Inject conversation history
        history_messages = context.get("history_messages", [])
        if history_messages:
            messages.extend(history_messages)
        else:
            # Fallback string injection
            conversation_history = context.get("conversation_history", "")
            if conversation_history:
                messages[0] = SystemMessage(
                    content=f"{system_prompt}\n\n## Previous Conversation:\n{conversation_history}"
                )
        
        # Add user query
        messages.append(HumanMessage(content=query))
        
        try:
            # Determine if we should force tool usage
            force_tool = self.should_force_tool(query)
            
            # Execute with appropriate tool_choice
            if force_tool:
                primary_tool = self.get_primary_tool_name()
                if primary_tool:
                    # Force specific tool usage
                    self.logger.debug("forcing-tool-usage", tool=primary_tool)
                    llm_for_call = self.llm.bind_tools(
                        self.tools,
                        tool_choice={"type": "function", "function": {"name": primary_tool}}
                    )
                else:
                    # Force any tool usage
                    llm_for_call = self.llm.bind_tools(self.tools, tool_choice="required")
            else:
                llm_for_call = self.llm_with_tools
            
            # First LLM call with timing
            llm_start = perf_counter()
            response = await llm_for_call.ainvoke(messages)
            llm_duration = perf_counter() - llm_start
            self.logger.debug(f"llm-call-completed", duration_ms=int(llm_duration * 1000))
            
            messages.append(response)
            
            # Process tool calls if any
            tool_call_count = 0
            max_iterations = 5
            
            while response.tool_calls and tool_call_count < max_iterations:
                tool_call_count += 1
                
                # Execute each tool call
                for tool_call in response.tool_calls:
                    tool_name = tool_call["name"]
                    tool_args = tool_call["args"]
                    
                    # Find and execute tool
                    tool = next((t for t in self.tools if t.name == tool_name), None)
                    if tool:
                        try:
                            tool_start = perf_counter()
                            
                            # Execute tool with timeout protection
                            tool_result = await asyncio.wait_for(
                                tool.ainvoke(tool_args),
                                timeout=self.settings.tool_timeout
                            )

                            # Global coverage enforcement handling:
                            # If the tool signals OUTSIDE_COVERAGE, stop and let the LLM craft the final user message.
                            if _is_outside_coverage_tool_result(tool_result):
                                response_text = await _render_outside_coverage_message(
                                    llm=self.llm,
                                    settings=self.settings,
                                    query=query,
                                    language=language,
                                    tool_result=tool_result,
                                )
                                total_duration = perf_counter() - start_time
                                agent_metrics.tool_calls = tool_call_count
                                agent_metrics.places_found = 0
                                metrics_collector.end_agent_execution(agent_metrics, success=True)
                                return {
                                    "response_text": response_text,
                                    "places": [],
                                    "tool_calls": tool_call_count,
                                    "reasoning_steps": len(messages),
                                    "agent_type": self.agent_type,
                                    "model_used": self.llm.model_name,
                                    "duration_ms": int(total_duration * 1000),
                                    "blocked_by_coverage": True,
                                    "coverage": tool_result.get("coverage"),
                                }
                            
                            tool_duration = perf_counter() - tool_start
                            self.logger.debug(
                                "tool-executed",
                                tool=tool_name,
                                duration_ms=int(tool_duration * 1000),
                            )
                            
                            # Add tool message
                            from langchain_core.messages import ToolMessage
                            messages.append(ToolMessage(
                                content=str(tool_result) if not isinstance(tool_result, str) else tool_result,
                                tool_call_id=tool_call["id"],
                            ))
                        except asyncio.TimeoutError:
                            self.logger.warning(
                                "tool-timeout",
                                tool=tool_name,
                                timeout=self.settings.tool_timeout,
                            )
                            from langchain_core.messages import ToolMessage
                            messages.append(ToolMessage(
                                content=f"Error: Tool {tool_name} timed out after {self.settings.tool_timeout}s",
                                tool_call_id=tool_call["id"],
                            ))
                        except Exception as e:
                            self.logger.error("tool-execution-failed", tool=tool_name, error=str(e))
                            from langchain_core.messages import ToolMessage
                            messages.append(ToolMessage(
                                content=f"Error: {str(e)}",
                                tool_call_id=tool_call["id"],
                            ))
                
                # Continue conversation with tool results
                response = await self.llm_with_tools.ainvoke(messages)
                messages.append(response)
            
            # Extract final response
            raw_response = response.content if hasattr(response, 'content') else str(response)
            final_answer = extract_final_answer(raw_response)
            response_text = clean_response_text(final_answer)
            
            # Extract places
            places = extract_places_from_messages(messages)
            
            # Validate and fix response consistency (count mismatch)
            if places:
                validator = get_response_validator()
                response_text = validator.validate_and_fix(
                    response_text, 
                    len(places), 
                    language
                )
            
            # Prepend unsupported language message if needed
            if unsupported_msg:
                response_text = f"{unsupported_msg}\n\n{response_text}"
            
            # Save places to DB
            if places:
                try:
                    places = await save_places_to_db(places, self.settings)
                    self.logger.info("places-saved-to-db", count=len(places))
                except Exception as exc:
                    self.logger.error("failed-to-save-places", error=str(exc))
            
            # Calculate total duration
            total_duration = perf_counter() - start_time
            
            # Update metrics
            agent_metrics.tool_calls = tool_call_count
            agent_metrics.places_found = len(places)
            metrics_collector.end_agent_execution(agent_metrics, success=True)
            
            self.logger.info(
                f"{self.agent_type}-agent-completed",
                tool_calls=tool_call_count,
                places_found=len(places),
                duration_ms=int(total_duration * 1000),
                has_response=bool(response_text),
            )
            
            return {
                "response_text": response_text,
                "places": places,
                "tool_calls": tool_call_count,
                "reasoning_steps": len(messages),
                "agent_type": self.agent_type,
                "model_used": self.llm.model_name,
                "duration_ms": int(total_duration * 1000),
            }
            
        except asyncio.TimeoutError as exc:
            duration = perf_counter() - start_time
            metrics_collector.end_agent_execution(agent_metrics, success=False, error=exc)
            
            self.logger.error(
                f"{self.agent_type}-agent-timeout",
                error="Request timed out",
                duration_ms=int(duration * 1000),
                timeout_config=str(self._timeout_config),
                query=query[:100],  # Truncate for logging
            )
            raise
            
        except Exception as exc:
            duration = perf_counter() - start_time
            metrics_collector.end_agent_execution(agent_metrics, success=False, error=exc)
            
            self.logger.error(
                f"{self.agent_type}-agent-failed",
                error=str(exc),
                error_type=type(exc).__name__,
                duration_ms=int(duration * 1000),
                query=query[:100],
            )
            raise


# ============================================================================
# Utility functions
# ============================================================================

def create_tool_forcing_prompt(query: str, tool_name: str, language: str = "es") -> str:
    """
    Create a prompt that encourages tool usage.
    
    Note: This is a fallback - prefer using tool_choice parameter.
    
    Args:
        query: Original query
        tool_name: Name of tool to encourage
        language: Response language
        
    Returns:
        Modified query with tool instruction
    """
    if language.startswith("es"):
        instruction = f"\n\n🔴 OBLIGATORIO: DEBES usar {tool_name} antes de responder."
    else:
        instruction = f"\n\n🔴 MANDATORY: You MUST use {tool_name} before responding."
    
    return f"{query}{instruction}"

