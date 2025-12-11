"""Registry of tools available to the agent.

🎯 BETA VERSION: Tools prioritize external APIs for real-time data.

Tool Categories:
1. SEARCH TOOLS - External API searches (Google Places, web, weather)
2. DATABASE TOOLS - Local fallback and analytics
3. PROCESSING TOOLS - Routing, scoring, itinerary generation
4. CONTEXT TOOLS - Memory and plan management
"""

from __future__ import annotations

from typing import List

from langchain_core.tools import BaseTool, tool

# Context and memory tools
from src.tools.context_tool import update_plan_context_tool

# Legacy tools (to be integrated/deprecated)
from src.tools.place_tool import search_places_tool
from src.tools.plan_tool import PlanTool

# NEW: Search tools (external APIs)
from src.tools.search import (
    google_places_tool,  # 🎯 BETA PRIMARY: Direct Google Places API
    web_search_tool,
    weather_api_tool,
)

# NEW: Database tools (fallback)
from src.tools.database import (
    search_local_db_fallback_tool,
    get_local_metrics_tool,
    get_user_preferences_tool,
)

# NEW: Processing tools
from src.tools.processing import (
    calculate_route_tool,
    generate_itinerary_tool,
    rank_by_score_tool,
)


# Initialize plan tool (legacy)
_plan_tool_instance = PlanTool()


@tool
async def create_itinerary_tool_legacy(
    query: str,
    city: str = "Zaragoza",
    num_locations: int = 3,
    plan_type: str = "casual",
) -> dict:
    """
    [LEGACY] Create an optimized itinerary plan with multiple locations in Zaragoza.
    
    ⚠️ NOTE: This is the legacy tool. The new generate_itinerary_tool provides
    more features and better integration with routing and scoring.
    
    🚧 BETA: Currently ONLY creates plans for Zaragoza, Spain.

    Args:
        query: Description of desired plan (e.g., "bar hopping", "tourist day")
        city: City name (MUST be "Zaragoza" - other cities not yet supported)
        num_locations: Number of locations to include (2-10, default: 3)
        plan_type: Type of plan - "quick", "casual", or "full_day"

    Returns:
        Complete itinerary with optimized route, time estimates, and recommendations
    """
    # BETA: Enforce Zaragoza only
    if city.lower() not in ["zaragoza", "zaragosa", "saragossa"]:
        return {
            "error": True,
            "message": f"⚠️ Currently we can only create plans in Zaragoza. Would you like to create a '{query}' plan in Zaragoza instead?"
        }
    
    # Force city to be Zaragoza
    city = "Zaragoza"
    
    try:
        itinerary = await _plan_tool_instance.create_plan(
            query=query,
            city=city,
            num_locations=num_locations,
            plan_type=plan_type,
        )
        return itinerary.model_dump()
    except Exception as e:
        return {
            "error": True,
            "message": f"Could not create plan: {str(e)}. Try with fewer locations or different plan type."
        }


def get_available_tools() -> List[BaseTool]:
    """
    Return the list of tools available for the agent.
    
    🎯 BETA VERSION - Tool Priority Order:
    
    SEARCH TOOLS (Real-time data):
    1. google_places_tool - PRIMARY search for places (Google Places API direct)
    2. web_search_tool - Web search for reviews, events, context
    3. weather_api_tool - Weather for indoor/outdoor recommendations
    
    PROCESSING TOOLS:
    4. calculate_route_tool - Route optimization and travel times
    5. rank_by_score_tool - Multi-factor scoring for recommendations
    6. generate_itinerary_tool - Advanced itinerary generation
    
    DATABASE TOOLS (Fallback/Analytics):
    7. search_local_db_fallback_tool - Query local cached data
    8. get_local_metrics_tool - B2B analytics
    9. get_user_preferences_tool - User preferences
    
    CONTEXT TOOLS:
    10. update_plan_context_tool - Save plan details to memory
    
    LEGACY TOOLS (Being phased out):
    11. search_places_tool - Old search (use google_places_tool instead)
    12. create_itinerary_tool_legacy - Old itinerary (use generate_itinerary_tool)
    """
    return [
        # PRIMARY SEARCH TOOLS (External APIs - Real-time)
        google_places_tool,           # 🎯 PRIMARY place search (Google Places API direct)
        web_search_tool,              # Web search for context
        weather_api_tool,             # Weather context
        
        # PROCESSING TOOLS
        calculate_route_tool,         # Routing and distances
        rank_by_score_tool,          # Smart scoring
        generate_itinerary_tool,     # Advanced itinerary
        
        # DATABASE TOOLS (Fallback/Analytics)
        search_local_db_fallback_tool,  # Local cache fallback
        get_local_metrics_tool,         # Analytics
        get_user_preferences_tool,      # User prefs
        
        # CONTEXT/MEMORY TOOLS
        update_plan_context_tool,    # Plan memory
        
        # LEGACY TOOLS (for backward compatibility)
        search_places_tool,          # Legacy search (via auphere-places Rust)
        create_itinerary_tool_legacy,  # Legacy itinerary
    ]


def get_core_tools() -> List[BaseTool]:
    """
    Get only the core tools (excluding legacy).
    Use this for new agent implementations.
    """
    return [
        # Search
        google_places_tool,
        web_search_tool,
        weather_api_tool,
        
        # Processing
        calculate_route_tool,
        rank_by_score_tool,
        generate_itinerary_tool,
        
        # Database
        search_local_db_fallback_tool,
        get_user_preferences_tool,
        
        # Context
        update_plan_context_tool,
    ]


def get_search_tools() -> List[BaseTool]:
    """
    Get tools for SearchAgent (focused search operations).
    
    Optimized for fast place lookups.
    """
    return [
        google_places_tool,           # PRIMARY search (Google Places API direct)
        web_search_tool,              # Additional context
        search_local_db_fallback_tool, # Fallback
    ]


def get_plan_tools() -> List[BaseTool]:
    """
    Get tools for PlanAgent (itinerary creation).
    
    Optimized for multi-location planning.
    """
    from src.tools.generate_plan_json_tool import generate_plan_json_tool
    
    return [
        google_places_tool,          # Find places (Google Places API direct)
        weather_api_tool,            # Weather context
        calculate_route_tool,        # Route optimization
        rank_by_score_tool,         # Rank options
        generate_itinerary_tool,    # Create itinerary
        generate_plan_json_tool,    # Generate structured JSON for frontend
        update_plan_context_tool,   # Save plan details
        search_local_db_fallback_tool, # Fallback
    ]


def get_recommend_tools() -> List[BaseTool]:
    """
    Get tools for RecommendAgent (recommendations and comparisons).
    
    Optimized for ranking and scoring.
    """
    return [
        google_places_tool,          # Find candidates (Google Places API direct)
        weather_api_tool,            # Weather context
        rank_by_score_tool,         # PRIMARY for recommendations
        web_search_tool,            # Reviews and context
        search_local_db_fallback_tool, # Fallback
    ]

