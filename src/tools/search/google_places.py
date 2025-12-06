"""
Google Places API tool for real-time official place data.

🎯 BETA VERSION: This is the PRIMARY search tool for places.
This tool queries Google Places API directly for the most up-to-date information.

Use this tool for:
- Real-time place searches
- Fresh ratings and reviews
- Current opening hours
- Live availability data
- Official business information

Falls back to local_db_fallback_tool if API fails or rate limited.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger
from src.utils.cache_manager import get_cache_manager

logger = get_logger("google_places_primary")


class GooglePlaceResult(BaseModel):
    """Result from Google Places API."""
    
    place_id: str
    name: str
    formatted_address: str
    location: Dict[str, float]  # lat, lng
    rating: Optional[float] = None
    user_ratings_total: Optional[int] = None
    price_level: Optional[int] = None
    types: List[str] = Field(default_factory=list)
    business_status: Optional[str] = None
    opening_hours: Optional[Dict[str, Any]] = None
    photos: Optional[List[str]] = Field(default_factory=list)


async def _search_google_places(
    api_key: str,
    query: str,
    location: str = "Zaragoza, Spain",
    radius: int = 5000,
    place_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Internal function to search Google Places API.
    
    API Docs: https://developers.google.com/maps/documentation/places/web-service/search-text
    """
    base_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
    
    # Build query parameters
    params = {
        "query": f"{query} in {location}",
        "key": api_key,
        "radius": radius,
        "language": "es",  # Return results in Spanish for Zaragoza
    }
    
    if place_type:
        params["type"] = place_type
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") != "OK":
            logger.error(f"Google Places API error: {data.get('status')} - {data.get('error_message', '')}")
            return {
                "status": data.get("status"),
                "error_message": data.get("error_message", "Unknown error"),
                "results": [],
            }
        
        return data


async def _get_place_details(api_key: str, place_id: str) -> Dict[str, Any]:
    """
    Get detailed information for a specific place.
    
    API Docs: https://developers.google.com/maps/documentation/places/web-service/details
    """
    base_url = "https://maps.googleapis.com/maps/api/place/details/json"
    
    params = {
        "place_id": place_id,
        "key": api_key,
        "fields": "name,rating,formatted_phone_number,opening_hours,website,photos,reviews,price_level,types",
        "language": "es",
    }
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") != "OK":
            logger.error(f"Place Details API error: {data.get('status')}")
            return {}
        
        return data.get("result", {})


@tool
async def google_places_tool(
    query: str,
    location: Optional[str] = "Zaragoza, Spain",
    radius: int = 5000,
    place_type: Optional[str] = None,
    max_results: int = 20,
    language: str = "es",
) -> Dict[str, Any]:
    """
    🎯 PRIMARY SEARCH TOOL: Search for places using Google Places API (real-time data).
    
    ⚠️ BETA VERSION: This is the MAIN tool for place searches. It provides:
    - Real-time, official place information from Google
    - Current ratings and review counts
    - Up-to-date contact information
    - Current opening hours and availability
    - Fresh photos
    
    This tool queries Google Places API directly for the freshest data.
    If the API fails or is rate-limited, the agent should fall back to
    search_local_db_fallback_tool for cached data.
    
    Args:
        query: Search query (e.g., "italian restaurant", "cocktail bar", "tapas")
        location: Location to search in (default: "Zaragoza, Spain")
        radius: Search radius in meters (default: 5000, max: 50000)
        place_type: Type of place (restaurant, bar, cafe, museum, park, etc.)
        max_results: Maximum results to return (default: 20)
        language: Language for results ("es" or "en")
    
    Returns:
        Dictionary with real-time place results from Google Places API
    
    Examples:
        - google_places_tool("italian restaurant", "Zaragoza, Spain")
        - google_places_tool("cocktail bar", place_type="bar", max_results=10)
        - google_places_tool("tapas", location="Zaragoza", radius=3000)
    
    Cost: ~$0.032 per request (Places API pricing)
    """
    settings = get_settings()
    
    # Check if API key is configured
    if not settings.google_places_api_key:
        logger.error("GOOGLE_PLACES_API_KEY not configured")
        return {
            "error": True,
            "message": "Google Places API key not configured. Please set GOOGLE_PLACES_API_KEY in environment variables. Fallback to search_local_db_fallback_tool.",
        }
    
    try:
        logger.info(f"[PRIMARY] Google Places API search: '{query}' near {location} (radius: {radius}m)")
        
        # Try to get from cache first (TTL: 1 hour for places)
        cache = await get_cache_manager()
        cache_key = cache._generate_key(
            "google_places",
            query=query,
            location=location,
            radius=radius,
            place_type=place_type,
            max_results=max_results,
            language=language,
        )
        
        cached_result = await cache.get(cache_key)
        if cached_result:
            logger.info(f"[CACHE HIT] Google Places: '{query}' near {location}")
            return cached_result
        
        # Search Google Places
        search_results = await _search_google_places(
            api_key=settings.google_places_api_key,
            query=query,
            location=location,
            radius=radius,
            place_type=place_type,
        )
        
        if "error_message" in search_results:
            logger.error(f"Google Places API error: {search_results['error_message']}")
            return {
                "error": True,
                "message": f"Google Places API error: {search_results['error_message']}. Try search_local_db_fallback_tool.",
            }
        
        # Process results
        results = search_results.get("results", [])[:max_results]
        
        processed_results = []
        for place in results:
            processed_place = {
                "place_id": place.get("place_id"),
                "name": place.get("name"),
                "address": place.get("formatted_address"),
                "location": {
                    "lat": place.get("geometry", {}).get("location", {}).get("lat"),
                    "lon": place.get("geometry", {}).get("location", {}).get("lng"),
                },
                "rating": place.get("rating"),
                "user_ratings_total": place.get("user_ratings_total"),
                "price_level": place.get("price_level"),
                "types": place.get("types", []),
                "business_status": place.get("business_status"),
                "open_now": place.get("opening_hours", {}).get("open_now"),
            }
            
            # Add photos if available
            if place.get("photos"):
                photo_reference = place["photos"][0].get("photo_reference")
                if photo_reference:
                    processed_place["photo_url"] = (
                        f"https://maps.googleapis.com/maps/api/place/photo"
                        f"?maxwidth=400&photo_reference={photo_reference}"
                        f"&key={settings.google_places_api_key}"
                    )
            
            processed_results.append(processed_place)
        
        logger.info(f"[PRIMARY] Found {len(processed_results)} places from Google Places API")
        
        result = {
            "query": query,
            "location": location,
            "results": processed_results,
            "total_results": len(processed_results),
            "source": "google_places_api",
            "cache_status": "fresh",
            "api_status": search_results.get("status", "OK"),
            "language": language,
        }
        
        # Cache the result for 1 hour (3600 seconds)
        await cache.set(cache_key, result, ttl=3600)
        
        return result
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP error in Google Places API: {str(e)}")
        logger.warning("Google Places API failed - agent should use search_local_db_fallback_tool")
        return {
            "error": True,
            "message": f"HTTP error calling Google Places API: {str(e)}. Try search_local_db_fallback_tool for cached data.",
        }
    except Exception as e:
        logger.error(f"Error in Google Places API search: {str(e)}")
        logger.warning("Google Places API failed - agent should use search_local_db_fallback_tool")
        return {
            "error": True,
            "message": f"Could not search Google Places API: {str(e)}. Try search_local_db_fallback_tool for cached data.",
        }

