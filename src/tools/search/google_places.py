"""Google Places API tool for direct place search.

🎯 BETA VERSION: Direct Google Places API integration for the agent.
This is the PRIMARY search tool during beta phase.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

import httpx
from langchain_core.tools import tool

from src.config.settings import get_settings
from src.utils.logger import get_logger

logger = get_logger("google_places_tool")
settings = get_settings()


class GooglePlacesClient:
    """Client for Google Places API (New) Text Search."""
    
    BASE_URL = "https://places.googleapis.com/v1/places:searchText"
    
    def __init__(self):
        self.api_key = settings.google_places_api_key
        if not self.api_key:
            logger.warning("google_places_api_key not configured")
    
    async def search_places(
        self,
        query: str,
        location: Optional[Dict[str, float]] = None,
        radius_meters: int = 5000,
        max_results: int = 10,
        language: str = "es",
    ) -> List[Dict[str, Any]]:
        """
        Search places using Google Places API (New).
        
        Args:
            query: Natural language query (e.g., "restaurantes chinos")
            location: Optional dict with lat/lng for location bias
            radius_meters: Search radius in meters (default: 5000m = 5km)
            max_results: Maximum number of results (default: 10)
            language: Response language code (default: "es")
        
        Returns:
            List of place dictionaries with normalized fields
        """
        if not self.api_key:
            logger.error("google_places_api_key not configured")
            return []
        
        try:
            # Build request body
            request_body = {
                "textQuery": query,
                "languageCode": language,
                "maxResultCount": min(max_results, 20),  # API limit is 20
            }
            
            # Add location bias if provided
            if location and "lat" in location and "lng" in location:
                request_body["locationBias"] = {
                    "circle": {
                        "center": {
                            "latitude": location["lat"],
                            "longitude": location["lng"],
                        },
                        "radius": radius_meters,
                    }
                }
            
            headers = {
                "Content-Type": "application/json",
                "X-Goog-Api-Key": self.api_key,
                "X-Goog-FieldMask": (
                    "places.id,"
                    "places.displayName,"
                    "places.formattedAddress,"
                    "places.location,"
                    "places.rating,"
                    "places.userRatingCount,"
                    "places.priceLevel,"
                    "places.types,"
                    "places.primaryType,"
                    "places.businessStatus,"
                    "places.googleMapsUri,"
                    "places.websiteUri,"
                    "places.internationalPhoneNumber,"
                    "places.photos"
                )
            }
            
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(
                    self.BASE_URL,
                    json=request_body,
                    headers=headers,
                )
                
                if response.status_code != 200:
                    logger.error(
                        "google_places_api_error",
                        status_code=response.status_code,
                        error=response.text,
                    )
                    return []
                
                data = response.json()
                places = data.get("places", [])
                
                # Normalize to consistent format
                normalized_places = []
                for place in places:
                    normalized = self._normalize_place(place)
                    normalized_places.append(normalized)
                
                logger.info(
                    "google_places_search_success",
                    query=query,
                    results_count=len(normalized_places),
                )
                
                return normalized_places
        
        except Exception as e:
            logger.error("google_places_search_failed", error=str(e), query=query)
            return []
    
    def _normalize_place(self, place: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize Google Places API response to consistent format."""
        location = place.get("location", {})
        display_name = place.get("displayName", {})
        formatted_address = place.get("formattedAddress", "")
        
        # Process photos to get image URLs
        images = []
        photos = place.get("photos", [])
        if photos and isinstance(photos, list):
            for photo in photos[:3]:  # Get up to 3 photos
                if isinstance(photo, dict) and photo.get("name"):
                    # Construct photo URL using Places API (new) format
                    photo_url = (
                        f"https://places.googleapis.com/v1/{photo['name']}/media"
                        f"?maxHeightPx=800&maxWidthPx=800&key={self.api_key}"
                    )
                    images.append(photo_url)
        
        # Extract neighborhood/district from address
        # Format: "C. de Ibiza, 23, Retiro, 28009 Madrid, España"
        # District is usually the 3rd part (index 2)
        neighborhood = None
        if formatted_address:
            parts = [p.strip() for p in formatted_address.split(",")]
            if len(parts) >= 3:
                # Try the district part (usually index 2)
                neighborhood = parts[2]
            elif len(parts) >= 2:
                # Fallback to second part
                neighborhood = parts[1]
        
        return {
            # Core fields
            "id": place.get("id"),
            "name": display_name.get("text", "Unknown"),
            "address": formatted_address,
            "latitude": location.get("latitude"),
            "longitude": location.get("longitude"),
            
            # Location details
            "neighborhood": neighborhood,
            
            # Ratings
            "rating": place.get("rating"),
            "user_ratings_total": place.get("userRatingCount", 0),
            
            # Categories
            "types": place.get("types", []),
            "primary_type": place.get("primaryType"),
            
            # Pricing
            "price_level": self._parse_price_level(place.get("priceLevel")),
            
            # Status
            "business_status": place.get("businessStatus", "OPERATIONAL"),
            
            # Links
            "google_maps_uri": place.get("googleMapsUri"),
            "website": place.get("websiteUri"),
            "phone": place.get("internationalPhoneNumber"),
            
            # Images
            "images": images,
            
            # Source
            "source": "google_places_api",
        }
    
    def _parse_price_level(self, price_level: Optional[str]) -> Optional[int]:
        """Convert Google's PRICE_LEVEL enum to numeric."""
        if not price_level:
            return None
        
        price_map = {
            "PRICE_LEVEL_FREE": 0,
            "PRICE_LEVEL_INEXPENSIVE": 1,
            "PRICE_LEVEL_MODERATE": 2,
            "PRICE_LEVEL_EXPENSIVE": 3,
            "PRICE_LEVEL_VERY_EXPENSIVE": 4,
        }
        
        return price_map.get(price_level)


# Singleton client
_client = GooglePlacesClient()


@tool
async def google_places_tool(
    query: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius_meters: int = 5000,
    max_results: int = 10,
    language: str = "es",
) -> dict:
    """
    🎯 PRIMARY SEARCH TOOL - Search for places using Google Places API.
    
    This is the main tool for finding restaurants, bars, venues, and any place
    the user is looking for. Use this FIRST for any place-related queries.
    
    Args:
        query: Natural language search query (e.g., "restaurantes chinos", "bares con música en vivo")
        latitude: Optional latitude for location-based search
        longitude: Optional longitude for location-based search
        radius_meters: Search radius in meters (default: 5000m = 5km)
        max_results: Maximum number of results to return (default: 10, max: 20)
        language: Response language code (default: "es" for Spanish)
    
    Returns:
        Dictionary with:
        - places: List of place dictionaries with details
        - count: Number of places found
        - query: Original query
        
    Examples:
        # Simple search
        google_places_tool(query="restaurantes italianos")
        
        # Location-based search
        google_places_tool(
            query="bares cerca de mí",
            latitude=40.4168,
            longitude=-3.7038,
            radius_meters=2000
        )
        
        # Specific query
        google_places_tool(
            query="restaurantes chinos con entrega a domicilio en Madrid",
            max_results=5
        )
    """
    try:
        # Build location dict if coordinates provided
        location = None
        if latitude is not None and longitude is not None:
            location = {"lat": latitude, "lng": longitude}
        
        # Search places
        places = await _client.search_places(
            query=query,
            location=location,
            radius_meters=radius_meters,
            max_results=max_results,
            language=language,
        )
        
        return {
            "success": True,
            "places": places,
            "count": len(places),
            "query": query,
            "location": location,
        }
    
    except Exception as e:
        logger.error("google_places_tool_error", error=str(e), query=query)
        return {
            "success": False,
            "places": [],
            "count": 0,
            "query": query,
            "error": str(e),
        }
