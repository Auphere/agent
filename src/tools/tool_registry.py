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

# Places SoT tools (auphere-places)
from src.tools.place_tool import places_search_tool, places_get_place_tool, places_clusters_tool

# Search tools (external APIs)
from src.tools.search import (
    google_places_tool,  # Fallback only (when auphere-places is unavailable)
    web_search_tool,
    weather_api_tool,
    geocode_city_tool,  # NEW: Geocoding
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


def get_available_tools() -> List[BaseTool]:
    """
    Return the list of tools available for the agent.
    
    🎯 BETA VERSION - Tool Priority Order:
    
    SEARCH TOOLS (Real-time data):
    1. geocode_city_tool - Geocode city/area to coordinates
    2. places_search_tool - PRIMARY search for places (auphere-places SoT)
    3. places_get_place_tool - PRIMARY detail (auphere-places SoT)
    4. google_places_tool - Fallback only if auphere-places is unavailable
    5. web_search_tool - Web search for reviews/events/context (optional)
    6. weather_api_tool - Weather for indoor/outdoor recommendations
    
    PROCESSING TOOLS:
    10. calculate_route_tool - Route optimization and travel times
    11. rank_by_score_tool - Multi-factor scoring for recommendations
    12. generate_itinerary_tool - Advanced itinerary generation
    
    DATABASE TOOLS (Fallback/Analytics):
    13. search_local_db_fallback_tool - Query local cached data
    14. get_local_metrics_tool - B2B analytics
    15. get_user_preferences_tool - User preferences
    
    CONTEXT TOOLS:
    16. update_plan_context_tool - Save plan details to memory
    
    Notes:
    - Social media scraping tools are intentionally excluded (out of scope).
    """
    return [
        # PRIMARY SEARCH TOOLS (External APIs - Real-time)
        geocode_city_tool,            # Geocode first when city provided
        places_search_tool,           # 🎯 PRIMARY place search (auphere-places SoT)
        places_get_place_tool,        # 🎯 PRIMARY place detail (auphere-places SoT)
        places_clusters_tool,         # Deterministic clustering (PostGIS)
        google_places_tool,           # Fallback only
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
        
    ]


def get_core_tools() -> List[BaseTool]:
    """
    Get only the core tools (excluding legacy).
    Use this for new agent implementations.
    """
    return [
        # Search
        places_search_tool,
        places_get_place_tool,
        places_clusters_tool,
        google_places_tool,  # fallback
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
        geocode_city_tool,            # Geocode bias
        places_search_tool,           # PRIMARY search (auphere-places SoT)
        places_get_place_tool,        # Detail for references
        places_clusters_tool,         # Cluster for zone-based suggestions (optional)
        google_places_tool,           # Fallback only
        web_search_tool,              # Additional context
        search_local_db_fallback_tool, # Fallback
    ]


def get_plan_tools() -> List[BaseTool]:
    """
    Get tools for PlanAgent (itinerary creation).
    
    Optimized for multi-location planning with rich data.
    """
    from src.tools.generate_plan_json_tool import generate_plan_json_tool
    
    return [
        geocode_city_tool,           # Geocode city/area
        places_search_tool,          # Find places (auphere-places SoT)
        places_get_place_tool,       # Detail (enrichment on-demand)
        places_clusters_tool,        # Cluster by zones (deterministic)
        google_places_tool,          # Fallback only
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
    
    Optimized for ranking and scoring with social proof.
    """
    return [
        places_search_tool,          # Find candidates (auphere-places SoT)
        places_get_place_tool,       # Detail on demand
        places_clusters_tool,        # Optional clustering
        google_places_tool,          # Fallback only
        weather_api_tool,            # Weather context
        rank_by_score_tool,         # PRIMARY for recommendations
        web_search_tool,            # Reviews and context
        search_local_db_fallback_tool, # Fallback
    ]

