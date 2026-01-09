"""Places tools that integrate with the Rust `auphere-places` microservice.

Phase 2: `auphere-places` is the Source of Truth (SoT) for:
- search (`GET /places/search`)
- detail (`GET /places/{id}`) with on-demand enrichment + persistence
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.tools.search.geocoding import resolve_country_from_location, check_coverage
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

    detected_types = detect_place_types(query_lower)

    # Check exact match first (e.g., "bares", "bar")
    if query_lower in TERM_MAPPING:
        api_term = TERM_MAPPING[query_lower]
        return api_term, api_term

    # If query contains exactly ONE known category keyword, keep original query (preserve modifiers)
    # and return the detected type for filtering.
    if len(detected_types) == 1:
        return query_clean, detected_types[0]

    # If query mentions multiple categories (e.g., "parques ... cafeterías"),
    # DO NOT force a single type filter — it can zero out results.
    return query_clean, None


def detect_place_types(query_lower: str) -> list[str]:
    """
    Best-effort detection of place categories mentioned in the query.

    Returns a stable-ordered list of API place types (e.g., ["park", "cafe"]).
    """
    if not query_lower:
        return []

    seen: set[str] = set()
    detected: list[str] = []
    for spanish_term, api_term in TERM_MAPPING.items():
        if spanish_term and spanish_term in query_lower:
            if api_term not in seen:
                seen.add(api_term)
                detected.append(api_term)
    return detected


class PlaceResult(BaseModel):
    """Structured result for a place from auphere-places (frontend-friendly)."""

    place_id: str = Field(description="Google Place ID (primary identifier)")
    name: str = Field(description="Place name")
    formatted_address: Optional[str] = Field(default=None, description="Full formatted address")
    vicinity: Optional[str] = Field(default=None, description="Short vicinity address")
    latitude: float = Field(description="Latitude")
    longitude: float = Field(description="Longitude")
    types: List[str] = Field(default_factory=list, description="Place types (Google)")
    rating: Optional[float] = Field(default=None, description="Google rating (0-5)")
    user_ratings_total: Optional[int] = Field(default=None, description="Number of ratings")
    price_level: Optional[int] = Field(default=None, description="Price level (0-4)")
    phone_number: Optional[str] = Field(default=None, description="Phone number")
    website: Optional[str] = Field(default=None, description="Website URL")
    opening_hours: Optional[Dict[str, Any]] = Field(default=None, description="Opening hours (raw)")
    is_open: Optional[bool] = Field(default=None, description="Open now")
    distance_km: Optional[float] = Field(default=None, description="Distance in km (if location search)")
    custom_attributes: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Frontend attributes (photos, tags, etc.)")
    
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
        city: Optional[str] = None,
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
            city: City name (optional, no default)
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
        detected_types = detect_place_types(query.strip().lower())

        # Use detected type if no explicit type provided (ONLY when unambiguous)
        if place_type is None:
            place_type = detected_type
        
        limit = max_results  # Alias for compatibility
        params: Dict[str, Any] = {"q": normalized_query, "limit": limit}

        # Prefer text search scoped by city when no coordinates are provided.
        if city:
            params["city"] = city
        
        # Add type filter if we have one (improves search accuracy)
        if place_type:
            params["type"] = place_type
        
        if lat is not None and lon is not None:
            params["lat"] = lat
            params["lon"] = lon
            params["radius_km"] = radius_km
        elif not city:
            # auphere-places requires either (city+q) or (lat+lon)
            raise ValueError("city is required when latitude/longitude are not provided")

        self.logger.info(
            "searching-places",
            query=query,
            normalized_query=normalized_query,
            place_type=place_type,
            city=city,
            has_location=(lat is not None and lon is not None),
        )

        try:
            async def _request(search_params: Dict[str, Any]) -> Dict[str, Any]:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.get(
                        f"{self.base_url}/places/search",
                        params=search_params,
                    )
                    response.raise_for_status()
                    return response.json()

            data = await _request(params)

            # auphere-places may return:
            # - FrontendSearchResponse: { places: [...] }
            # - SearchResponse (DB fallback): { data: [...] }
            def _extract_places(payload: Dict[str, Any]) -> List[Dict[str, Any]]:
                places_data = payload.get("places")
                if places_data is None:
                    places_data = payload.get("data", [])
                return places_data or []

            def _parse_places(raw_places: List[Dict[str, Any]]) -> List[PlaceResult]:
                parsed: List[PlaceResult] = []
                for place_dict in raw_places:
                    try:
                        parsed.append(PlaceResult(**place_dict))
                    except Exception as parse_error:
                        self.logger.warning(
                            "failed-to-parse-place",
                            place_name=place_dict.get("name", "unknown"),
                            error=str(parse_error),
                        )
                return parsed

            places = _parse_places(_extract_places(data))

            # Retry strategy (only when search returns empty but we detected categories):
            # - If the user query is broad (e.g., "lugares románticos...") the upstream service
            #   may return 0. In that case, retry using detected type keywords as q/type.
            if not places and detected_types:
                for retry_type in detected_types[:3]:
                    retry_params = dict(params)
                    retry_params["q"] = retry_type
                    retry_params["type"] = retry_type
                    self.logger.info(
                        "places-search-retry",
                        reason="empty_results_using_detected_type",
                        retry_type=retry_type,
                        city=city,
                        has_location=(lat is not None and lon is not None),
                    )
                    retry_data = await _request(retry_params)
                    places = _parse_places(_extract_places(retry_data))
                    if places:
                        break

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
def _to_place_normalized(place: PlaceResult) -> Dict[str, Any]:
    primary_photo_url = None
    if isinstance(place.custom_attributes, dict):
        primary_photo_url = place.custom_attributes.get("primary_photo_url")

    return {
        "id": place.place_id,
        "name": place.name,
        "address": place.formatted_address or place.vicinity or "",
        "latitude": place.latitude,
        "longitude": place.longitude,
        # PlaceNormalized shape expected by scoring/place_normalizer
        "location": {"lat": place.latitude, "lon": place.longitude, "lng": place.longitude},
        "neighborhood": None,  # can be derived later if needed
        "rating": place.rating,
        "user_ratings_total": place.user_ratings_total or 0,
        "types": place.types or [],
        "primary_type": (place.types[0] if place.types else None),
        "price_level": place.price_level,
        "open_now": place.is_open,
        "business_status": "OPERATIONAL",
        "google_maps_uri": None,
        "website": place.website,
        "phone": place.phone_number,
        "images": [primary_photo_url] if primary_photo_url else [],
        "source": "auphere_places",
    }


@tool
async def places_search_tool(
    query: str,
    city: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius_meters: int = 5000,
    max_results: int = 10,
) -> dict:
    """
    🎯 PRIMARY Places Search Tool (SoT) — search via `auphere-places`.

    Uses:
    - `GET /places/search` (Google Places when configured, DB fallback otherwise)

    Args:
        query: Natural language query (e.g., "tapas", "bares con música")
        city: City name for text search when no coordinates are provided
        latitude/longitude: Optional coordinates for nearby bias
        radius_meters: Nearby search radius (default 5000m)
        max_results: Max results (default 10)

    Returns:
        { success, places, count, query, location }
        where places[] are normalized to the same shape used by google_places_tool.
    """
    tool_instance = PlaceSearchTool()
    try:
        # MVP Coverage enforcement (global): block searches outside configured coverage.
        settings = get_settings()
        if settings.coverage_enabled and settings.coverage_countries_list:
            country = await resolve_country_from_location(
                city=city,
                latitude=latitude,
                longitude=longitude,
            )
            if country and country.get("country_code"):
                is_covered, _ = check_coverage(country["country_code"])
                if not is_covered:
                    return {
                        "success": False,
                        "places": [],
                        "count": 0,
                        "query": query,
                        "location": {"lat": latitude, "lon": longitude, "lng": longitude}
                        if latitude is not None and longitude is not None
                        else None,
                        "error": "OUTSIDE_COVERAGE",
                        "coverage": {
                            "country_code": country["country_code"],
                            "country_name": country.get("country_name", ""),
                            "allowed_countries": settings.coverage_countries_list,
                        },
                    }

        radius_km = max(1, int(round(radius_meters / 1000)))
        places = await tool_instance.search_places(
            query=query,
            city=city,
            lat=latitude,
            lon=longitude,
            radius_km=radius_km,
            max_results=max_results,
        )

        normalized = [_to_place_normalized(p) for p in places]
        location = None
        if latitude is not None and longitude is not None:
            # requirements.location is expected to use {lat, lon}
            location = {"lat": latitude, "lon": longitude, "lng": longitude}

        return {
            "success": True,
            "places": normalized,
            "count": len(normalized),
            "query": query,
            "location": location,
        }
    except Exception as e:
        return {
            "success": False,
            "places": [],
            "count": 0,
            "query": query,
            "location": {"lat": latitude, "lng": longitude}
            if latitude is not None and longitude is not None
            else None,
            "error": str(e),
        }


@tool
async def places_get_place_tool(place_id: str) -> dict:
    """
    Get place detail from `auphere-places` by Google Place ID (recommended) or UUID.

    Uses:
    - `GET /places/{id}` which can trigger on-demand enrichment + persistence.
    """
    settings = get_settings()
    logger = get_logger("places-get-place", settings=settings)
    base_url = settings.places_api_url
    timeout = settings.places_api_timeout

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url}/places/{place_id}")
            resp.raise_for_status()
            data = resp.json()

        # Flattened response: { ...placeFields, photos: [], reviews: [], tips: [] }
        place_obj = dict(data)
        photos = place_obj.pop("photos", []) or []
        reviews = place_obj.pop("reviews", []) or []
        tips = place_obj.pop("tips", []) or []

        # Convert to a minimal normalized place (compatible with google_places_tool output)
        lat = place_obj.get("latitude")
        lon = place_obj.get("longitude")

        # MVP Coverage enforcement (global): block details outside coverage.
        settings = get_settings()
        if settings.coverage_enabled and settings.coverage_countries_list and lat is not None and lon is not None:
            country = await resolve_country_from_location(latitude=float(lat), longitude=float(lon))
            if country and country.get("country_code"):
                is_covered, _ = check_coverage(country["country_code"])
                if not is_covered:
                    return {
                        "success": False,
                        "error": "OUTSIDE_COVERAGE",
                        "place_id": place_id,
                        "coverage": {
                            "country_code": country["country_code"],
                            "country_name": country.get("country_name", ""),
                            "allowed_countries": settings.coverage_countries_list,
                        },
                    }

        normalized = {
            "id": place_obj.get("google_place_id") or place_id,
            "name": place_obj.get("name"),
            "address": place_obj.get("formatted_address") or place_obj.get("address") or "",
            "latitude": lat,
            "longitude": lon,
            "location": {"lat": lat, "lon": lon, "lng": lon} if lat is not None and lon is not None else None,
            "neighborhood": place_obj.get("district"),
            "rating": place_obj.get("google_rating"),
            "user_ratings_total": place_obj.get("google_rating_count", 0),
            "types": [place_obj.get("type")] if place_obj.get("type") else [],
            "primary_type": place_obj.get("type"),
            "price_level": place_obj.get("price_level"),
            "open_now": place_obj.get("open_now") or place_obj.get("is_open"),
            "business_status": place_obj.get("business_status"),
            "website": place_obj.get("website"),
            "phone": place_obj.get("phone_number") or place_obj.get("phone"),
            "images": [
                p.get("url")
                for p in photos[:3]
                if isinstance(p, dict) and p.get("url")
            ],
            "source": "auphere_places_detail",
            "enrichment": {"photos": photos, "reviews": reviews, "tips": tips},
        }

        return {"success": True, "place": normalized}
    except httpx.HTTPStatusError as e:
        logger.error("places-get-place-http-error", status_code=e.response.status_code, error=str(e))
        return {"success": False, "error": str(e), "place_id": place_id}
    except Exception as e:
        logger.error("places-get-place-error", error=str(e))
        return {"success": False, "error": str(e), "place_id": place_id}


@tool
async def places_clusters_tool(
    city: Optional[str] = None,
    place_type: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    radius_meters: Optional[int] = None,
    eps_m: Optional[float] = None,
    min_points: Optional[int] = None,
    limit_places: Optional[int] = None,
    limit_clusters: Optional[int] = None,
) -> dict:
    """
    Cluster places into "zones" using auphere-places PostGIS DBSCAN.

    Uses:
    - `GET /places/clusters`

    Notes:
    - This is DB-only clustering (fast, deterministic) and helps reduce tokens upstream.
    """
    settings = get_settings()
    logger = get_logger("places-clusters", settings=settings)
    base_url = settings.places_api_url
    timeout = settings.places_api_timeout

    params: Dict[str, Any] = {}
    if city:
        params["city"] = city
    if place_type:
        params["type"] = place_type
    if latitude is not None and longitude is not None:
        params["lat"] = latitude
        params["lon"] = longitude
    if radius_meters is not None:
        params["radius_km"] = max(1, int(round(radius_meters / 1000)))
    if eps_m is not None:
        params["eps_m"] = eps_m
    if min_points is not None:
        params["min_points"] = min_points
    if limit_places is not None:
        params["limit_places"] = limit_places
    if limit_clusters is not None:
        params["limit_clusters"] = limit_clusters

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.get(f"{base_url}/places/clusters", params=params)
            resp.raise_for_status()
            data = resp.json()
        return {"success": True, **data}
    except httpx.HTTPStatusError as e:
        logger.error("places-clusters-http-error", status_code=e.response.status_code, error=str(e))
        return {"success": False, "error": str(e)}
    except Exception as e:
        logger.error("places-clusters-error", error=str(e))
        return {"success": False, "error": str(e)}


# Backward compatible aliases (older code refers to these names)
search_places_tool = places_search_tool
PlaceTool = PlaceSearchTool

