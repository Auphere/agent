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

import operator
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TypedDict, Annotated, Sequence

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
    - Common LLM initialization
    - Tool binding with tool_choice support
    - Consistent logging
    - Cache integration
    - Place extraction and saving
    - Response cleaning
    
    Subclasses must implement:
    - get_tools(): Return list of tools for this agent
    - get_system_prompt(): Return system prompt for this agent
    - agent_type: Property returning agent type name
    """
    
    def __init__(
        self,
        model_name: str = "gpt-4o-mini",
        temperature: float = 0.5,
        timeout: int = 30,
        settings: Settings | None = None,
    ) -> None:
        """
        Initialize base agent.
        
        Args:
            model_name: OpenAI model to use
            temperature: LLM temperature
            timeout: Request timeout in seconds
            settings: Application settings
        """
        self.settings = settings or get_settings()
        self.logger = get_logger(f"{self.agent_type}-agent", settings=self.settings)
        
        # Initialize LLM
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=temperature,
            api_key=self.settings.openai_api_key,
            timeout=timeout,
            max_retries=1,
            request_timeout=timeout,
        )
        
        # Get tools for this agent type
        self.tools = self.get_tools()
        
        # Create LLM with tools bound
        self.llm_with_tools = self.llm.bind_tools(self.tools)
        
        self.logger.info(
            f"{self.agent_type}-agent-initialized",
            model=model_name,
            tools_count=len(self.tools),
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
        return "google_places_tool"
    
    async def run(
        self,
        query: str,
        language: str = "es",
        context: Dict[str, Any] | None = None,
    ) -> Dict[str, Any]:
        """
        Execute the agent.
        
        Args:
            query: User query
            language: Response language
            context: Additional context
            
        Returns:
            Dict with response_text, places, and metadata
        """
        context = context or {}
        
        self.logger.info(
            f"{self.agent_type}-agent-starting",
            query=query,
            language=language,
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
            
            # First LLM call
            response = await llm_for_call.ainvoke(messages)
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
                            tool_result = await tool.ainvoke(tool_args)
                            
                            # Add tool message
                            from langchain_core.messages import ToolMessage
                            messages.append(ToolMessage(
                                content=str(tool_result) if not isinstance(tool_result, str) else tool_result,
                                tool_call_id=tool_call["id"],
                            ))
                        except Exception as e:
                            self.logger.error(f"tool-execution-failed", tool=tool_name, error=str(e))
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
            
            # Save places to DB
            if places:
                try:
                    places = await save_places_to_db(places, self.settings)
                    self.logger.info("places-saved", count=len(places))
                except Exception as exc:
                    self.logger.error("failed-to-save-places", error=str(exc))
            
            self.logger.info(
                f"{self.agent_type}-agent-completed",
                tool_calls=tool_call_count,
                places_found=len(places),
            )
            
            return {
                "response_text": response_text,
                "places": places,
                "tool_calls": tool_call_count,
                "reasoning_steps": len(messages),
                "agent_type": self.agent_type,
                "model_used": self.llm.model_name,
            }
            
        except Exception as exc:
            self.logger.error(
                f"{self.agent_type}-agent-failed",
                error=str(exc),
                query=query,
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

