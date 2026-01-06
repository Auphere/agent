"""RecommendAgent - Specialized agent for recommendations and comparisons."""

from __future__ import annotations

from typing import Any, Dict, List

from langchain_core.tools import BaseTool

from src.agents.specialized.base_agent import BaseSpecializedAgent
from src.agents.prompts.recommend_prompts import get_recommend_agent_prompt
from src.config.settings import Settings
from src.tools.tool_registry import get_recommend_tools


class RecommendAgent(BaseSpecializedAgent):
    """
    Specialized agent optimized for recommendations and comparisons.
    
    Characteristics:
    - Uses gpt-4o-mini (fast and cost-effective)
    - Focuses on google_places_tool + rank_by_score_tool
    - Opinionated, helpful responses
    - Uses bind_tools with tool_choice for reliable tool usage
    
    Best for:
    - "What's the best X?"
    - "Recommend Y"
    - "Compare A and B"
    - "Top 5 places for Z"
    """
    
    @property
    def agent_type(self) -> str:
        return "recommend"

    def __init__(self, settings: Settings | None = None) -> None:
        """Initialize RecommendAgent with balanced settings."""
        super().__init__(
            model_name="gpt-4o-mini",
            temperature=0.5,  # Medium for balanced recommendations
            timeout=20,  # Slightly longer for recommendations
            settings=settings,
        )

    def get_tools(self) -> List[BaseTool]:
        """Return recommendation-specific tools."""
        return get_recommend_tools()

    def get_system_prompt(self, context: Dict[str, Any], language: str) -> str:
        """Return recommendation-optimized system prompt."""
        return get_recommend_agent_prompt(context, language)

    def should_force_tool(self, query: str) -> bool:
        """
        RecommendAgent needs tools when asking for recommendations.
        
        Force tool usage for queries about:
        - Recommendations (recomienda, suggest, recommend)
        - Best/top places (mejor, best, top)
        - Comparisons (compare, cual es mejor)
        - Specific activities (cenar, dinner, drinks)
        """
        query_lower = query.lower()
        
        # Recommendation actions
        recommend_actions = [
            "recomienda", "recomiéndame", "sugiéreme", "sugiere",
            "recommend", "suggest", "advise",
            "quiero", "necesito", "buscando",
            "dame", "dime", "cuál", "cual",
        ]
        
        # Quality/ranking indicators
        quality_words = [
            "mejor", "mejores", "best", "top",
            "bueno", "buenos", "good", "great",
            "favorito", "favorite", "popular",
            "recomendado", "recommended",
        ]
        
        # Activity indicators
        activities = [
            "cenar", "cena", "dinner", "comer", "comida",
            "lunch", "almuerzo", "desayuno", "breakfast",
            "tomar", "beber", "drinks", "copa", "cerveza",
            "salir", "go out", "plan", "planes",
        ]
        
        # Place types
        place_types = [
            "restaurante", "restaurant", "bar", "cafe", "café",
            "club", "lugar", "sitio", "place", "spot",
        ]
        
        has_recommend = any(action in query_lower for action in recommend_actions)
        has_quality = any(word in query_lower for word in quality_words)
        has_activity = any(act in query_lower for act in activities)
        has_place = any(place in query_lower for place in place_types)
        
        # Force tool for recommendations, quality queries, or activities with places
        return has_recommend or has_quality or (has_activity and has_place) or has_activity

    def get_primary_tool_name(self) -> str:
        """RecommendAgent primarily uses google_places_tool to find places to recommend."""
        return "google_places_tool"
