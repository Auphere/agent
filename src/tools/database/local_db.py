"""
Database fallback tool for querying local PostgreSQL via Rust microservice.

⚠️ BETA VERSION NOTE:
This tool is a FALLBACK. The primary search should use google_places_tool
for real-time data. This tool queries the local auphere-places PostgreSQL
database which contains synced/cached data.

Use local DB for:
- Fallback when Google Places API fails
- Analytics and metrics queries
- Performance optimization (cached data)
- Offline mode
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger("local_db_fallback_tool")


@tool
async def search_local_db_fallback_tool(
    query: str,
    city: str = "Zaragoza",
    place_type: Optional[str] = None,
    min_rating: Optional[float] = None,
    max_results: int = 20,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    radius_km: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Search the local PostgreSQL database for cached place data (FALLBACK TOOL).
    
    ⚠️ IMPORTANT: This is a FALLBACK tool. For beta version, prefer google_places_tool
    for real-time data. Use this tool only when:
    - Google Places API fails or is unavailable
    - Need cached/historical data
    - Need analytics metrics
    - Performance optimization required
    
    This queries the auphere-places Rust microservice which serves data
    from local PostgreSQL (synced from Google Places).
    
    Args:
        query: Search query (e.g., "italian restaurant", "cocktail bar", "tapas")
        city: City to search in (currently only "Zaragoza" supported)
        place_type: Specific place type (bar, restaurant, cafe, museum, park)
        min_rating: Minimum rating (0-5)
        max_results: Maximum number of results (default: 20)
        lat: Latitude for proximity search
        lon: Longitude for proximity search
        radius_km: Search radius in kilometers (if lat/lon provided)
    
    Returns:
        Dictionary with cached place results from local database
    
    Examples:
        - search_local_db_fallback_tool("italian restaurant", "Zaragoza")
        - search_local_db_fallback_tool("bar", city="Zaragoza", min_rating=4.0)
    """
    settings = get_settings()
    
    try:
        logger.info(f"Local DB fallback search: {query} in {city}")
        logger.warning("Using local DB fallback - consider using google_places_tool for real-time data")
        
        # TODO: Call the auphere-places Rust microservice /places/search endpoint
        # This should use PLACES_API_URL from settings
        
        return {
            "query": query,
            "city": city,
            "results": [],
            "total_results": 0,
            "source": "local_cache",
            "message": "Local DB fallback tool - queries cached data. Use google_places_tool for real-time data.",
        }
        
    except Exception as e:
        logger.error(f"Error in local DB fallback search: {str(e)}")
        return {
            "error": True,
            "message": f"Could not search local database: {str(e)}",
        }

