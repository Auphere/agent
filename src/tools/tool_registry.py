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
    search_foursquare_places,  # NEW: Foursquare v2 (105M POIs)
    get_foursquare_place_enrichment,  # NEW: Foursquare details
    scrape_instagram_place,  # NEW: Instagram scraping
    scrape_tiktok_place,  # NEW: TikTok scraping
    scrape_tripadvisor_reviews,  # NEW: TripAdvisor scraping
    get_social_media_summary,  # NEW: Combined social media data
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
    1. geocode_city_tool - Geocode city/area to coordinates
    2. google_places_tool - PRIMARY search for places (Google Places API direct)
    3. search_foursquare_places - 105M+ global POIs with rich metadata
    4. get_foursquare_place_enrichment - Detailed Foursquare data
    5. web_search_tool - Web search for reviews, events, context
    6. weather_api_tool - Weather for indoor/outdoor recommendations
    
    SOCIAL MEDIA ENRICHMENT:
    6. scrape_instagram_place - Instagram posts and trends
    7. scrape_tiktok_place - TikTok videos and viral content
    8. scrape_tripadvisor_reviews - Detailed reviews
    9. get_social_media_summary - Combined social media data
    
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
    
    LEGACY TOOLS (Being phased out):
    17. search_places_tool - Old search (use google_places_tool instead)
    18. create_itinerary_tool_legacy - Old itinerary (use generate_itinerary_tool)
    """
    return [
        # PRIMARY SEARCH TOOLS (External APIs - Real-time)
        geocode_city_tool,            # Geocode first when city provided
        google_places_tool,           # 🎯 PRIMARY place search (Google Places API direct)
        search_foursquare_places,     # NEW: Foursquare 105M+ POIs
        get_foursquare_place_enrichment,  # NEW: Foursquare details
        web_search_tool,              # Web search for context
        weather_api_tool,             # Weather context
        
        # SOCIAL MEDIA ENRICHMENT (NEW)
        scrape_instagram_place,       # Instagram posts
        scrape_tiktok_place,          # TikTok videos
        scrape_tripadvisor_reviews,   # TripAdvisor reviews
        get_social_media_summary,     # Combined social media
        
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
        search_foursquare_places,
        get_foursquare_place_enrichment,
        web_search_tool,
        weather_api_tool,
        
        # Social Media
        scrape_instagram_place,
        scrape_tiktok_place,
        scrape_tripadvisor_reviews,
        get_social_media_summary,
        
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
        google_places_tool,           # PRIMARY search (Google Places API direct)
        search_foursquare_places,     # Foursquare 105M POIs
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
        google_places_tool,          # Find places (Google Places API direct)
        search_foursquare_places,    # Foursquare rich POI data
        get_foursquare_place_enrichment,  # Detailed place info
        scrape_instagram_place,      # Visual content
        scrape_tiktok_place,         # Trending content
        scrape_tripadvisor_reviews,  # Reviews
        get_social_media_summary,    # Combined social data
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
        google_places_tool,          # Find candidates (Google Places API direct)
        search_foursquare_places,    # Foursquare data
        get_foursquare_place_enrichment,  # Detailed info
        weather_api_tool,            # Weather context
        rank_by_score_tool,         # PRIMARY for recommendations
        scrape_instagram_place,      # Social proof
        scrape_tripadvisor_reviews,  # Reviews
        web_search_tool,            # Reviews and context
        search_local_db_fallback_tool, # Fallback
    ]

