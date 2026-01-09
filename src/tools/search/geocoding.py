"""Lightweight geocoding tool to convert city/area names into coordinates + country metadata."""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

import httpx
from langchain_core.tools import tool

from src.config.settings import get_settings
from src.utils.cache_manager import get_cache_manager
from src.utils.logger import get_logger


logger = get_logger("geocode_city_tool")


_http_client: httpx.AsyncClient | None = None


def _get_http_client() -> httpx.AsyncClient:
    """Reuse a single AsyncClient to benefit from connection pooling."""
    global _http_client
    if _http_client is None:
        _http_client = httpx.AsyncClient(
            timeout=8.0,
            headers={"User-Agent": "auphere-agent/1.0"},
        )
    return _http_client

# Country code mapping for common country names
COUNTRY_NAME_TO_CODE = {
    "spain": "ES",
    "españa": "ES",
    "portugal": "PT",
    "france": "FR",
    "francia": "FR",
    "italy": "IT",
    "italia": "IT",
    "germany": "DE",
    "alemania": "DE",
    "united kingdom": "GB",
    "reino unido": "GB",
    "netherlands": "NL",
    "países bajos": "NL",
    "belgium": "BE",
    "bélgica": "BE",
    "switzerland": "CH",
    "suiza": "CH",
    "austria": "AT",
    "greece": "GR",
    "grecia": "GR",
    "morocco": "MA",
    "marruecos": "MA",
    "united states": "US",
    "estados unidos": "US",
    "mexico": "MX",
    "méxico": "MX",
    "argentina": "AR",
    "colombia": "CO",
    "chile": "CL",
    "peru": "PE",
    "perú": "PE",
}


async def _geocode_city_full(city: str) -> Optional[Dict[str, Any]]:
    """
    Resolve a city/area name into lat/lon and country using Nominatim (OSM).
    
    Returns:
        Dict with latitude, longitude, country_code, country_name, display_name
        or None if geocoding failed.
    """
    if not city or not city.strip():
        return None

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": city,
        "format": "json",
        "limit": 1,
        "addressdetails": 1,  # Include address breakdown with country
    }
    try:
        settings = get_settings()
        cache = await get_cache_manager()

        city_norm = city.strip()

        async def _fetch() -> Optional[Dict[str, Any]]:
            client = _get_http_client()
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None

            item = data[0]
            address = item.get("address", {})

            # Extract country code (Nominatim returns it in address.country_code)
            country_code = address.get("country_code", "").upper()
            country_name = address.get("country", "")

            return {
                "latitude": float(item["lat"]),
                "longitude": float(item["lon"]),
                "country_code": country_code,
                "country_name": country_name,
                "display_name": item.get("display_name", city_norm),
            }

        # Cache successful geocodes aggressively; Nominatim is rate-limited and stable.
        return await cache.get_or_set("geocode_city", _fetch, 86400, city_norm)
    except Exception as exc:
        logger.warning("geocode_city_failed", city=city, error=str(exc))
        return None


async def _geocode_city(city: str) -> Optional[Dict[str, float]]:
    """Legacy function for backward compatibility - returns only coordinates."""
    result = await _geocode_city_full(city)
    if not result:
        return None
    return {"latitude": result["latitude"], "longitude": result["longitude"]}


async def _reverse_geocode_country(latitude: float, longitude: float) -> Optional[Dict[str, str]]:
    """
    Reverse geocode lat/lon to country metadata using Nominatim.

    Returns:
        {country_code, country_name} or None.
    """
    url = "https://nominatim.openstreetmap.org/reverse"
    params = {
        "lat": latitude,
        "lon": longitude,
        "format": "json",
        "zoom": 3,  # country level
        "addressdetails": 1,
    }
    try:
        cache = await get_cache_manager()

        async def _fetch() -> Optional[Dict[str, str]]:
            client = _get_http_client()
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            address = (data or {}).get("address", {}) if isinstance(data, dict) else {}
            country_code = str(address.get("country_code", "")).upper()
            country_name = str(address.get("country", ""))
            if not country_code:
                return None
            return {"country_code": country_code, "country_name": country_name}

        # Cache reverse-geocodes strongly; country lookup is very stable.
        return await cache.get_or_set("reverse_geocode_country", _fetch, 604800, latitude, longitude)
    except Exception as exc:
        logger.warning(
            "reverse-geocode-failed",
            latitude=latitude,
            longitude=longitude,
            error=str(exc),
        )
        return None


async def resolve_country_from_location(
    *,
    city: Optional[str] = None,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
) -> Optional[Dict[str, str]]:
    """Resolve country metadata for either a city string or coordinates."""
    if latitude is not None and longitude is not None:
        return await _reverse_geocode_country(latitude, longitude)
    if city:
        data = await _geocode_city_full(city)
        if not data:
            return None
        return {
            "country_code": str(data.get("country_code") or "").upper(),
            "country_name": str(data.get("country_name") or ""),
        }
    return None


def check_coverage(country_code: str) -> tuple[bool, str]:
    """
    Check if a country is within the configured coverage area.
    
    Args:
        country_code: ISO 3166-1 alpha-2 country code (e.g., "ES", "IT")
    
    Returns:
        Tuple of (is_covered: bool, allowed_countries_csv: str)
    """
    settings = get_settings()
    
    # If coverage is disabled, allow everything
    if not settings.coverage_enabled:
        return True, settings.coverage_countries
    
    # If no countries configured, allow everything
    allowed_countries = settings.coverage_countries_list
    if not allowed_countries:
        return True, settings.coverage_countries
    
    # Check if country is in allowed list
    if country_code.upper() in allowed_countries:
        return True, settings.coverage_countries
    
    return False, settings.coverage_countries


@tool
async def geocode_city_tool(city: str) -> str:
    """
    Geocode a city/area name into latitude and longitude using OpenStreetMap.
    
    Also validates if the location is within the service coverage area.
    Returns a JSON string so the agent can reason deterministically.

    Args:
        city: Name of the city or area (e.g., "Madrid", "Barcelona, Spain", "Florencia, Italia").

    Returns:
        JSON string with:
        - ok: bool
        - latitude/longitude when ok
        - country_code/country_name when ok
        - is_within_coverage: bool when ok
        - allowed_countries: list[str] (ISO alpha-2) when coverage is enabled
        - error: str when not ok
    """
    result = await _geocode_city_full(city)
    if not result:
        return json.dumps(
            {
                "ok": False,
                "error": "GEOCODE_FAILED",
                "query": city,
            }
        )

    # Check coverage
    settings = get_settings()
    is_covered, _ = check_coverage(result["country_code"])
    allowed = settings.coverage_countries_list if settings.coverage_enabled else []
    
    if not is_covered:
        logger.info(
            "location-outside-coverage",
            city=city,
            country_code=result["country_code"],
            country_name=result["country_name"],
            allowed_countries=allowed,
        )

    return json.dumps(
        {
            "ok": True,
            "query": city,
            "display_name": result.get("display_name", city),
            "latitude": result["latitude"],
            "longitude": result["longitude"],
            "country_code": result["country_code"],
            "country_name": result["country_name"],
            "is_within_coverage": bool(is_covered),
            "allowed_countries": allowed,
            "coverage_enabled": bool(settings.coverage_enabled),
        }
    )

