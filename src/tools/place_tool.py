"""Place search tool that integrates with the Rust Places microservice."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger


# ============================================================
# TERM MAPPING: Spanish terms → English API terms
# This mapping is used to translate user queries to API-compatible terms
# ============================================================
TERM_MAPPING: Dict[str, str] = {
    # Bares
    "bares": "bar",
    "bar": "bar",
    "bars": "bar",
    "pub": "bar",
    "pubs": "bar",
    "taberna": "bar",
    "tabernas": "bar",
    "cervecería": "bar",
    "cervecerías": "bar",
    "coctelería": "bar",
    "coctelerías": "bar",
    # Restaurantes
    "restaurantes": "restaurant",
    "restaurante": "restaurant",
    "restaurants": "restaurant",
    "restaurant": "restaurant",
    "comida": "restaurant",
    "comer": "restaurant",
    "cenar": "restaurant",
    "almorzar": "restaurant",
    "tapas": "restaurant",
    "tapa": "restaurant",
    # Cafeterías
    "cafeterías": "cafe",
    "cafetería": "cafe",
    "cafés": "cafe",
    "café": "cafe",
    "cafes": "cafe",
    "cafe": "cafe",
    "coffee": "cafe",
    "desayuno": "cafe",
    "desayunar": "cafe",
    # Museos
    "museos": "museum",
    "museo": "museum",
    "museums": "museum",
    "museum": "museum",
    "galería": "museum",
    "galerías": "museum",
    "arte": "museum",
    "cultura": "museum",
    # Parques
    "parques": "park",
    "parque": "park",
    "parks": "park",
    "park": "park",
    "jardín": "park",
    "jardines": "park",
    "naturaleza": "park",
    "pasear": "park",
    # Tiendas / Centros comerciales
    "tiendas": "shopping_mall",
    "tienda": "shopping_mall",
    "compras": "shopping_mall",
    "shopping": "shopping_mall",
    "centro comercial": "shopping_mall",
    "centros comerciales": "shopping_mall",
    "mall": "shopping_mall",
    # Hoteles
    "hoteles": "lodging",
    "hotel": "lodging",
    "hotels": "lodging",
    "alojamiento": "lodging",
    "hospedaje": "lodging",
    "hostal": "lodging",
    "hostales": "lodging",
    "dormir": "lodging",
}

# Reverse mapping for display (API term → Spanish display name)
TYPE_DISPLAY_NAMES: Dict[str, str] = {
    "bar": "bar",
    "restaurant": "restaurante",
    "cafe": "cafetería",
    "museum": "museo",
    "park": "parque",
    "shopping_mall": "centro comercial",
    "lodging": "hotel",
    "nightclub": "discoteca",
    "other": "lugar",
}


def normalize_query(query: str) -> tuple[str, Optional[str]]:
    """
    Normalize a Spanish query to English API term without losing modifiers.
    
    Args:
        query: User query in Spanish or English
        
    Returns:
        Tuple of (search_query, place_type) where place_type is for filtering.
        The search_query preserves adjectives like "asiática", "italiana", etc.
    """
    query_clean = query.strip()
    query_lower = query_clean.lower()
    
    # Check exact match first (e.g., "bares", "bar")
    if query_lower in TERM_MAPPING:
        api_term = TERM_MAPPING[query_lower]
        return api_term, api_term
    
    # If query contains a known keyword, keep the original query for the search
    # but still return the detected place type for filtering.
    for spanish_term, api_term in TERM_MAPPING.items():
        if spanish_term in query_lower:
            return query_clean, api_term
    
    # No match found, return original
    return query_clean, None


class PlaceResult(BaseModel):
    """Structured result for a place from Rust API."""

    id: str = Field(description="Place UUID")
    name: str = Field(description="Place name")
    type: str = Field(description="Place type (restaurant, bar, etc.)")
    location: Optional[List[float]] = Field(default=None, description="Coordinates as [longitude, latitude]")
    city: str = Field(description="City name")
    district: Optional[str] = Field(default=None, description="District/neighborhood")
    google_rating: Optional[float] = Field(default=None, description="Google rating (0-5)")
    google_rating_count: Optional[int] = Field(default=None, description="Number of ratings")
    main_categories: List[str] = Field(default_factory=list, description="Main categories")
    website: Optional[str] = Field(default=None, description="Website URL")
    primary_photo_url: Optional[str] = Field(default=None, description="Primary photo URL")
    primary_photo_thumbnail_url: Optional[str] = Field(default=None, description="Thumbnail photo URL")
    tags: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional tags")
    vibe_descriptor: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Vibe descriptors")
    is_subscribed: Optional[bool] = Field(default=False, description="Subscription status")
    created_at: Optional[str] = Field(default=None, description="Creation timestamp")
    
    # Helper properties for backward compatibility
    @property
    def address(self) -> str:
        """Generate a simple address string."""
        parts = [self.name, self.city]
        if self.district:
            parts.insert(1, self.district)
        return ", ".join(parts)
    
    @property
    def latitude(self) -> float:
        """Extract latitude from location array."""
        return self.location[1] if len(self.location) > 1 else 0.0
    
    @property
    def longitude(self) -> float:
        """Extract longitude from location array."""
        return self.location[0] if len(self.location) > 0 else 0.0
    
    model_config = {"extra": "ignore"}  # Ignore extra fields from API


class PlaceSearchTool:
    """Tool for searching places via the Rust Places API."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.logger = get_logger("place-tool", settings=self.settings)
        self.base_url = self.settings.places_api_url
        self.timeout = self.settings.places_api_timeout

    async def search_places(
        self,
        query: str,
        city: str = "Zaragoza",
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        radius_km: int = 5,
        max_results: int = 5,
        place_type: Optional[str] = None,
    ) -> List[PlaceResult]:
        """
        Search for places using the Rust microservice.
        
        Args:
            query: Search query (e.g., "bares", "restaurantes")
            city: City name (default: Zaragoza)
            lat: Latitude for geo-search
            lon: Longitude for geo-search
            radius_km: Search radius in kilometers
            max_results: Maximum number of results
            place_type: Optional place type filter (bar, restaurant, cafe, etc.)
            
        Returns:
            List of PlaceResult objects with name, address, rating, etc.
        """
        # Normalize query (translate Spanish → English API terms)
        normalized_query, detected_type = normalize_query(query)
        
        # Use detected type if no explicit type provided
        if place_type is None:
            place_type = detected_type
        
        limit = max_results  # Alias for compatibility
        params = {
            "q": normalized_query,
            "city": city,
            "limit": limit,
        }
        
        # Add type filter if we have one (improves search accuracy)
        if place_type:
            params["type"] = place_type
        
        if lat is not None and lon is not None:
            params["lat"] = lat
            params["lon"] = lon
            params["radius_km"] = radius_km

        self.logger.info(
            "searching-places",
            query=query,
            normalized_query=normalized_query,
            place_type=place_type,
            city=city,
            has_location=bool(lat and lon),
        )

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/places/search",
                    params=params,
                )
                response.raise_for_status()
                data = response.json()
                
                # Rust API returns "data" field
                places_data = data.get("data", [])
                
                # Convert to PlaceResult objects
                places = []
                for place_dict in places_data:
                    try:
                        places.append(PlaceResult(**place_dict))
                    except Exception as parse_error:
                        self.logger.warning(
                            "failed-to-parse-place",
                            place_name=place_dict.get("name", "unknown"),
                            error=str(parse_error),
                        )
                        continue
                
                self.logger.info("places-found", count=len(places))
                return places

        except httpx.HTTPStatusError as exc:
            self.logger.error(
                "places-api-http-error",
                status_code=exc.response.status_code,
                error=str(exc),
            )
            return []
        except httpx.RequestError as exc:
            self.logger.error("places-api-connection-error", error=str(exc))
            return []
        except Exception as exc:
            self.logger.error("places-search-failed", error=str(exc), exc_info=True)
            return []


# LangChain tool wrapper for use in agents
@tool
async def search_places_tool(
    query: str,
    city: str = "Zaragoza",
    limit: int = 5,
) -> str:
    """
    Search for places like restaurants, bars, museums, etc. in Zaragoza.
    
    🚧 BETA: Currently ONLY searches in Zaragoza, Spain. Do not use for other cities.
    
    Use this tool when the user wants to find specific venues or locations in Zaragoza.
    
    Args:
        query: What type of place to search. Use English terms for best results:
               - "bar" for bars, pubs, taverns
               - "restaurant" for restaurants, tapas places
               - "cafe" for cafeterias, coffee shops
               - "museum" for museums, galleries
               - "park" for parks, gardens
               - "lodging" for hotels, hostels
        city: City to search in (MUST be "Zaragoza" - other cities not yet supported)
        limit: Maximum number of results (default: 5, max: 20)
        
    Returns:
        Formatted string with real place results from database, or message if no results found
        
    Example:
        search_places_tool("bar", "Zaragoza", 5)
        search_places_tool("restaurant", "Zaragoza", 10)
    """
    # BETA: Enforce Zaragoza only
    if city.lower() not in ["zaragoza", "zaragosa", "saragossa"]:
        return f"⚠️ Por el momento solo tenemos información de lugares en Zaragoza. No puedo buscar en '{city}' todavía. ¿Te gustaría buscar '{query}' en Zaragoza?"
    
    # Force city to be Zaragoza
    city = "Zaragoza"
    
    # Create tool instance and search (normalization happens inside search_places)
    tool_instance = PlaceSearchTool()
    places = await tool_instance.search_places(query=query, city=city, max_results=limit)
    
    if not places:
        # Provide helpful suggestions based on known types
        suggestions = "bar, restaurant, cafe, museum, park, lodging"
        return f"No se encontraron lugares para '{query}' en {city}. Intenta buscar por tipo: {suggestions}"
    
    # Format results as readable text for the LLM
    result_lines = [f"Encontré {len(places)} lugares en {city}:"]
    for idx, place in enumerate(places, 1):
        name = place.name
        rating = place.google_rating
        # Get Spanish display name for type
        place_type_display = TYPE_DISPLAY_NAMES.get(place.type, place.type or "lugar")
        
        line = f"{idx}. {name}"
        if place_type_display:
            line += f" ({place_type_display})"
        if rating:
            line += f" - ⭐ {rating}/5"
        if place.google_rating_count:
            line += f" ({place.google_rating_count} reseñas)"
        
        result_lines.append(line)
    
    return "\n".join(result_lines)


# Alias for compatibility
PlaceTool = PlaceSearchTool

