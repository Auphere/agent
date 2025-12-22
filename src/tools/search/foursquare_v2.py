"""
Foursquare Places API (FSQ API) integration tool.

Provides access to 105M+ POIs globally with:
- Place search and details
- Reviews and tips
- Photos and media
- Real-time crowdedness data
- Opening hours
- Ratings and popularity metrics
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger
from src.tools.search.geocoding import _geocode_city

logger = get_logger("foursquare_v2")


class FoursquarePlace(BaseModel):
    """Structured Foursquare place data."""
    
    fsq_id: str = Field(description="Foursquare place ID")
    name: str = Field(description="Place name")
    categories: List[str] = Field(default_factory=list, description="Place categories")
    location: Dict[str, Any] = Field(default_factory=dict, description="Location data")
    distance: Optional[int] = Field(default=None, description="Distance in meters")
    rating: Optional[float] = Field(default=None, description="Rating (0-10)")
    popularity: Optional[float] = Field(default=None, description="Popularity score")
    price: Optional[int] = Field(default=None, description="Price level (1-4)")
    hours: Optional[Dict[str, Any]] = Field(default=None, description="Opening hours")
    photos: List[str] = Field(default_factory=list, description="Photo URLs")
    tips: List[str] = Field(default_factory=list, description="User tips/reviews")
    crowdedness: Optional[Dict[str, Any]] = Field(default=None, description="Crowdedness data")
    
    model_config = {"extra": "allow"}


class FoursquareClient:
    """Client for Foursquare Places API v3."""
    
    BASE_URL = "https://api.foursquare.com/v3"
    
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.logger = get_logger("foursquare_client")
        self.headers = {
            "Authorization": api_key,
            "Accept": "application/json",
        }
    
    async def search_places(
        self,
        query: str,
        lat: float,
        lon: float,
        radius: int = 5000,
        limit: int = 10,
        categories: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Search for places near a location.
        
        Args:
            query: Search query
            lat: Latitude
            lon: Longitude
            radius: Search radius in meters (max 100000)
            limit: Number of results (max 50)
            categories: Comma-separated category IDs
            
        Returns:
            List of place dictionaries
        """
        params = {
            "query": query,
            "ll": f"{lat},{lon}",
            "radius": min(radius, 100000),
            "limit": min(limit, 50),
            "sort": "RELEVANCE",
            "fields": "fsq_id,name,categories,location,distance,rating,popularity,price,hours,photos,tips",
        }
        
        if categories:
            params["categories"] = categories
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/places/search",
                    headers=self.headers,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                
                results = data.get("results", [])
                self.logger.info(
                    "foursquare-search-success",
                    query=query,
                    results_count=len(results),
                )
                return results
                
        except httpx.HTTPStatusError as exc:
            self.logger.error(
                "foursquare-api-error",
                status_code=exc.response.status_code,
                error=str(exc),
            )
            return []
        except Exception as exc:
            self.logger.error("foursquare-search-failed", error=str(exc))
            return []
    
    async def get_place_details(
        self,
        fsq_id: str,
        fields: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Get detailed information about a place.
        
        Args:
            fsq_id: Foursquare place ID
            fields: Comma-separated field names (default: all)
            
        Returns:
            Place details dictionary or None if not found
        """
        if fields is None:
            fields = "fsq_id,name,categories,location,rating,popularity,price,hours,photos,tips,description,tel,website,email,social_media"
        
        params = {"fields": fields}
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/places/{fsq_id}",
                    headers=self.headers,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                
                self.logger.info("foursquare-details-success", fsq_id=fsq_id)
                return data
                
        except httpx.HTTPStatusError as exc:
            self.logger.error(
                "foursquare-details-error",
                fsq_id=fsq_id,
                status_code=exc.response.status_code,
            )
            return None
        except Exception as exc:
            self.logger.error("foursquare-details-failed", fsq_id=fsq_id, error=str(exc))
            return None
    
    async def get_place_photos(self, fsq_id: str, limit: int = 10) -> List[str]:
        """
        Get photos for a place.
        
        Args:
            fsq_id: Foursquare place ID
            limit: Number of photos (max 50)
            
        Returns:
            List of photo URLs
        """
        params = {"limit": min(limit, 50)}
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/places/{fsq_id}/photos",
                    headers=self.headers,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                
                photos = []
                for photo in data:
                    prefix = photo.get("prefix", "")
                    suffix = photo.get("suffix", "")
                    if prefix and suffix:
                        # Use 'original' size for best quality
                        photos.append(f"{prefix}original{suffix}")
                
                self.logger.info("foursquare-photos-success", fsq_id=fsq_id, count=len(photos))
                return photos
                
        except Exception as exc:
            self.logger.error("foursquare-photos-failed", fsq_id=fsq_id, error=str(exc))
            return []
    
    async def get_place_tips(self, fsq_id: str, limit: int = 10) -> List[str]:
        """
        Get user tips/reviews for a place.
        
        Args:
            fsq_id: Foursquare place ID
            limit: Number of tips (max 50)
            
        Returns:
            List of tip texts
        """
        params = {
            "limit": min(limit, 50),
            "sort": "POPULAR",
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    f"{self.BASE_URL}/places/{fsq_id}/tips",
                    headers=self.headers,
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                
                tips = [tip.get("text", "") for tip in data if tip.get("text")]
                
                self.logger.info("foursquare-tips-success", fsq_id=fsq_id, count=len(tips))
                return tips
                
        except Exception as exc:
            self.logger.error("foursquare-tips-failed", fsq_id=fsq_id, error=str(exc))
            return []


# LangChain tool wrappers
@tool
async def search_foursquare_places(
    query: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    city: Optional[str] = None,
    radius: int = 5000,
    limit: int = 10,
) -> str:
    """
    Search for places using Foursquare's 105M+ global POI database.
    
    This tool provides access to:
    - Detailed place information (name, category, location)
    - Ratings and popularity metrics
    - Opening hours
    - Price levels
    - Real-time crowdedness data
    - Photos and user tips
    
    Use this tool when you need comprehensive place data beyond basic search results.
    Foursquare has excellent coverage globally and provides rich metadata.
    
    Args:
        query: What to search for (e.g., "coffee shop", "romantic restaurant")
        latitude: Center point latitude
        longitude: Center point longitude
        city: Optional city/area name (used to geocode if coords are not provided)
        radius: Search radius in meters (default: 5000, max: 100000)
        limit: Number of results (default: 10, max: 50)
        
    Returns:
        Formatted string with place results including ratings, tips, and details
        
    Example:
        search_foursquare_places("italian restaurant", 41.65, -0.88, 3000, 5)
    """
    settings = get_settings()
    
    if not settings.foursquare_api_key:
        return "❌ Foursquare API key not configured. Please set FOURSQUARE_API_KEY."
    
    # If coords missing, try geocode from city or fallback map
    lat = latitude
    lon = longitude
    if (lat is None or lon is None) and city:
        coords = await _geocode_city(city)
        if coords:
            lat = coords["latitude"]
            lon = coords["longitude"]
    if (lat is None or lon is None) and city:
        fallback = get_city_coordinates(city)
        if fallback:
            lat, lon = fallback
    
    if lat is None or lon is None:
        return "❌ No hay coordenadas disponibles; especifica ciudad o coordenadas."
    
    client = FoursquareClient(settings.foursquare_api_key)
    
    results = await client.search_places(
        query=query,
        lat=lat,
        lon=lon,
        radius=radius,
        limit=limit,
    )
    
    if not results:
        return f"No se encontraron lugares para '{query}' en Foursquare."
    
    # Format results
    output_lines = [f"Encontré {len(results)} lugares en Foursquare:"]
    
    for idx, place in enumerate(results, 1):
        name = place.get("name", "Unknown")
        categories = place.get("categories", [])
        category_names = [cat.get("name", "") for cat in categories]
        category_str = ", ".join(category_names) if category_names else "N/A"
        
        rating = place.get("rating")
        popularity = place.get("popularity")
        price = place.get("price")
        distance = place.get("distance")
        
        line = f"{idx}. {name} ({category_str})"
        
        if rating:
            line += f" - ⭐ {rating}/10"
        
        if popularity:
            line += f" - 🔥 Popularidad: {popularity:.1f}"
        
        if price:
            line += f" - 💰 Precio: {'$' * price}"
        
        if distance:
            line += f" - 📍 {distance}m"
        
        output_lines.append(line)
        
        # Add location details
        location = place.get("location", {})
        address = location.get("formatted_address", location.get("address", ""))
        if address:
            output_lines.append(f"   📍 {address}")
    
    return "\n".join(output_lines)


@tool
async def get_foursquare_place_enrichment(
    fsq_id: str,
    include_photos: bool = True,
    include_tips: bool = True,
) -> str:
    """
    Get enriched data for a specific Foursquare place including photos, tips, and detailed info.
    
    Use this tool when you need more details about a specific place found in search results.
    This provides:
    - Full place details (description, contact, website)
    - High-quality photos
    - User tips and reviews
    - Social media links
    - Opening hours details
    
    Args:
        fsq_id: Foursquare place ID (from search results)
        include_photos: Include photo URLs (default: True)
        include_tips: Include user tips/reviews (default: True)
        
    Returns:
        Formatted string with enriched place data
        
    Example:
        get_foursquare_place_enrichment("4b123abc", True, True)
    """
    settings = get_settings()
    
    if not settings.foursquare_api_key:
        return "❌ Foursquare API key not configured."
    
    client = FoursquareClient(settings.foursquare_api_key)
    
    # Get place details
    details = await client.get_place_details(fsq_id)
    
    if not details:
        return f"❌ No se pudo obtener información del lugar {fsq_id}"
    
    name = details.get("name", "Unknown")
    output_lines = [f"📍 {name}", ""]
    
    # Basic info
    categories = details.get("categories", [])
    if categories:
        category_names = [cat.get("name", "") for cat in categories]
        output_lines.append(f"Categorías: {', '.join(category_names)}")
    
    rating = details.get("rating")
    if rating:
        output_lines.append(f"Rating: ⭐ {rating}/10")
    
    popularity = details.get("popularity")
    if popularity:
        output_lines.append(f"Popularidad: 🔥 {popularity:.1f}")
    
    price = details.get("price")
    if price:
        output_lines.append(f"Precio: {'$' * price}")
    
    # Contact info
    tel = details.get("tel")
    if tel:
        output_lines.append(f"Teléfono: {tel}")
    
    website = details.get("website")
    if website:
        output_lines.append(f"Web: {website}")
    
    # Description
    description = details.get("description")
    if description:
        output_lines.append(f"\nDescripción: {description}")
    
    # Opening hours
    hours = details.get("hours")
    if hours:
        output_lines.append("\nHorarios:")
        # Simplified hours display
        if isinstance(hours, dict):
            display_hours = hours.get("display", "Ver en la app")
            output_lines.append(f"  {display_hours}")
    
    # Photos
    if include_photos:
        photos = await client.get_place_photos(fsq_id, limit=5)
        if photos:
            output_lines.append(f"\nFotos ({len(photos)}):")
            for photo_url in photos[:3]:  # Show first 3
                output_lines.append(f"  - {photo_url}")
    
    # Tips
    if include_tips:
        tips = await client.get_place_tips(fsq_id, limit=5)
        if tips:
            output_lines.append(f"\nReseñas populares ({len(tips)}):")
            for tip in tips[:3]:  # Show first 3
                output_lines.append(f"  - \"{tip}\"")
    
    return "\n".join(output_lines)


# Convenience function to get coordinates from city name
async def get_city_coordinates(city: str) -> Optional[tuple[float, float]]:
    """
    Get approximate coordinates for a city name.
    
    Args:
        city: City name
        
    Returns:
        Tuple of (latitude, longitude) or None
    """
    # Hardcoded common cities (in production, use a geocoding service)
    cities_coords = {
        "zaragoza": (41.6488, -0.8891),
        "madrid": (40.4168, -3.7038),
        "barcelona": (41.3851, 2.1734),
        "valencia": (39.4699, -0.3763),
        "sevilla": (37.3891, -5.9845),
        "bilbao": (43.2630, -2.9350),
        "málaga": (36.7213, -4.4214),
        "murcia": (37.9922, -1.1307),
        "palma": (39.5696, 2.6502),
        "las palmas": (28.1248, -15.4302),
        "new york": (40.7128, -74.0060),
        "london": (51.5074, -0.1278),
        "paris": (48.8566, 2.3522),
        "tokyo": (35.6762, 139.6503),
        "istanbul": (41.0082, 28.9784),
    }
    
    city_lower = city.lower().strip()
    return cities_coords.get(city_lower)

