"""Lightweight geocoding tool to convert city/area names into coordinates."""

from __future__ import annotations

from typing import Dict, Optional

import httpx
from langchain_core.tools import tool

from src.utils.logger import get_logger


logger = get_logger("geocode_city_tool")


async def _geocode_city(city: str) -> Optional[Dict[str, float]]:
    """Resolve a city/area name into lat/lon using Nominatim (OSM)."""
    if not city or not city.strip():
        return None

    url = "https://nominatim.openstreetmap.org/search"
    params = {
        "q": city,
        "format": "json",
        "limit": 1,
    }
    headers = {"User-Agent": "auphere-agent/1.0"}

    try:
        async with httpx.AsyncClient(timeout=8.0, headers=headers) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            data = resp.json()
            if not data:
                return None
            item = data[0]
            return {"latitude": float(item["lat"]), "longitude": float(item["lon"])}
    except Exception as exc:
        logger.warning("geocode_city_failed", city=city, error=str(exc))
        return None


@tool
async def geocode_city_tool(city: str) -> str:
    """
    Geocode a city/area name into latitude and longitude using OpenStreetMap.

    Args:
        city: Name of the city or area (e.g., "Madrid", "Barcelona, Spain").

    Returns:
        String with coordinates or an error message.
    """
    coords = await _geocode_city(city)
    if not coords:
        return f"❌ No se pudieron obtener coordenadas para '{city}'."

    return f"✅ Coordenadas para {city}: lat={coords['latitude']}, lon={coords['longitude']}"

