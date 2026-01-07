"""SearchAgent - Specialized agent for fast place searches."""

from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.tools import BaseTool

from src.agents.specialized.base_agent import BaseSpecializedAgent
from src.agents.prompts.search_prompts import get_search_agent_prompt
from src.config.settings import Settings, get_settings
from src.tools.tool_registry import get_search_tools


class SearchAgent(BaseSpecializedAgent):
    """
    Specialized agent optimized for fast place searches.
    
    Characteristics:
    - Uses gpt-4o-mini (fast, cheap)
    - Focuses on google_places_tool
    - Quick, concise responses
    - Minimal reasoning steps
    - Uses bind_tools with tool_choice for reliable tool usage
    - Timeout: 60s (standard) for fast searches
    
    Best for:
    - "Find X in Y"
    - "Show me places"
    - "Search for..."
    """
    
    @property
    def agent_type(self) -> str:
        return "search"

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize SearchAgent with fast model and search tools."""
        _settings = settings or get_settings()
        
        super().__init__(
            model_name="gpt-4o-mini",
            temperature=0.3,  # Lower for consistent searches
            # Standard timeout for fast searches
            timeout=(
                _settings.llm_connection_timeout,
                _settings.llm_read_timeout_standard
            ),
            max_retries=_settings.llm_max_retries,
            settings=_settings,
        )

    def get_tools(self) -> List[BaseTool]:
        """Return search-specific tools."""
        return get_search_tools()

    def get_system_prompt(self, context: Dict[str, Any], language: str) -> str:
        """Return search-optimized system prompt."""
        return get_search_agent_prompt(context, language)

    def should_force_tool(self, query: str) -> bool:
        """
        SearchAgent almost always needs to use google_places_tool.
        
        Force tool usage for any query mentioning:
        - Search actions (busca, encuentra, search, find)
        - Places (restaurante, bar, lugar, place)
        - Locations (en, in, cerca, near)
        """
        query_lower = query.lower()
        
        # Action words that require search
        search_actions = [
            "busca", "encuentra", "muestra", "dame", "dime",
            "search", "find", "show", "give me", "tell me",
            "quiero", "necesito", "buscando",
            "looking for", "need", "want",
        ]
        
        # Place type indicators
        place_types = [
            "restaurante", "restaurant", "bar", "cafe", "café",
            "club", "discoteca", "pub", "lugar", "sitio",
            "place", "spot", "hotel", "museo", "museum",
            "tienda", "shop", "store", "parque", "park",
        ]
        
        # Location indicators
        location_words = [
            "en ", "cerca", "near", "around", "in ",
            "por ", "zone", "zona", "área", "area",
        ]
        
        has_action = any(action in query_lower for action in search_actions)
        has_place = any(place in query_lower for place in place_types)
        has_location = any(loc in query_lower for loc in location_words)
        
        # Force tool if has search action, or has place type + location
        return has_action or (has_place and has_location) or has_place

    def get_primary_tool_name(self) -> str:
        """SearchAgent primarily uses google_places_tool."""
        return "google_places_tool"
