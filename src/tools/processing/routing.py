"""
Route calculation tool using Google Maps Directions API for distances, travel times, and transport options.

Use for:
- Calculating optimal routes between multiple places
- Estimating travel time
- Getting turn-by-turn directions
- Optimizing visit order
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger("routing_tool")


class RouteSegment(BaseModel):
    """A segment of the route between two points."""
    
    from_location: Dict[str, float]
    to_location: Dict[str, float]
    distance_meters: int
    duration_seconds: int
    mode: str


async def _calculate_distance_matrix(
    api_key: str,
    origins: List[Dict[str, float]],
    destinations: List[Dict[str, float]],
    mode: str = "walking",
) -> Dict[str, Any]:
    """
    Calculate distance matrix using Google Maps Distance Matrix API.
    
    API Docs: https://developers.google.com/maps/documentation/distance-matrix
    """
    base_url = "https://maps.googleapis.com/maps/api/distancematrix/json"
    
    # Format coordinates
    origins_str = "|".join([f"{o['lat']},{o['lon']}" for o in origins])
    destinations_str = "|".join([f"{d['lat']},{d['lon']}" for d in destinations])
    
    params = {
        "origins": origins_str,
        "destinations": destinations_str,
        "mode": mode,
        "key": api_key,
        "language": "es",
    }
    
    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        if data.get("status") != "OK":
            raise Exception(f"Distance Matrix API error: {data.get('status')}")
        
        return data


def _optimize_route_order(
    origin: Dict[str, float],
    destinations: List[Dict[str, float]],
    distance_matrix: Dict[str, Any],
) -> List[int]:
    """
    Simple greedy algorithm to optimize route order (nearest neighbor).
    For production, consider using Google's waypoint optimization or more sophisticated algorithms.
    """
    if len(destinations) <= 1:
        return list(range(len(destinations)))
    
    # Greedy nearest neighbor
    unvisited = set(range(len(destinations)))
    route = []
    current_idx = -1  # Start from origin
    
    while unvisited:
        min_distance = float('inf')
        next_idx = None
        
        for dest_idx in unvisited:
            # Get distance from current to destination
            if current_idx == -1:
                # From origin
                distance = distance_matrix["rows"][0]["elements"][dest_idx].get("distance", {}).get("value", float('inf'))
            else:
                # From previous destination
                distance = distance_matrix["rows"][current_idx + 1]["elements"][dest_idx].get("distance", {}).get("value", float('inf'))
            
            if distance < min_distance:
                min_distance = distance
                next_idx = dest_idx
        
        if next_idx is not None:
            route.append(next_idx)
            unvisited.remove(next_idx)
            current_idx = next_idx
    
    return route


@tool
async def calculate_route_tool(
    origin: Dict[str, float],
    destinations: List[Dict[str, float]],
    mode: str = "walking",
    optimize: bool = True,
    language: str = "es",
) -> Dict[str, Any]:
    """
    Calculate optimal route between multiple locations using Google Maps.
    
    Use this tool to:
    - Calculate distances and travel times between places
    - Optimize the order of visits (nearest neighbor algorithm)
    - Get total trip duration and distance
    - Plan efficient itineraries
    
    Args:
        origin: Starting point {"lat": float, "lon": float}
        destinations: List of destination points [{"lat": float, "lon": float}, ...]
        mode: Transport mode ("walking", "driving", "transit", "bicycling")
        optimize: Whether to optimize route order (default: True)
        language: Language for directions ("es" or "en")
    
    Returns:
        Optimized route with distances, travel times, and segments
    
    Examples:
        - calculate_route_tool({"lat": 41.65, "lon": -0.89}, [{"lat": 41.66, "lon": -0.88}])
        - calculate_route_tool(origin, destinations, mode="walking", optimize=True)
    """
    settings = get_settings()
    
    # Check if API key is configured
    if not settings.google_maps_api_key:
        logger.warning("GOOGLE_MAPS_API_KEY not configured")
        return {
            "error": True,
            "message": "Google Maps API key not configured. Please set GOOGLE_MAPS_API_KEY in environment variables.",
        }
    
    try:
        logger.info(f"Calculating route for {len(destinations)} destinations, mode: {mode}, optimize: {optimize}")
        
        if not destinations:
            return {
                "error": True,
                "message": "No destinations provided.",
            }
        
        # Calculate distance matrix
        all_points = [origin] + destinations
        distance_matrix = await _calculate_distance_matrix(
            api_key=settings.google_maps_api_key,
            origins=all_points,
            destinations=destinations,
            mode=mode,
        )
        
        # Optimize route order if requested
        if optimize and len(destinations) > 1:
            optimized_indices = _optimize_route_order(origin, destinations, distance_matrix)
            optimized_destinations = [destinations[i] for i in optimized_indices]
        else:
            optimized_indices = list(range(len(destinations)))
            optimized_destinations = destinations
        
        # Build route segments
        route_segments = []
        total_distance_meters = 0
        total_duration_seconds = 0
        
        current_point = origin
        for i, dest_idx in enumerate(optimized_indices):
            dest = destinations[dest_idx]
            
            # Get distance and duration from matrix
            if i == 0:
                # From origin to first destination
                element = distance_matrix["rows"][0]["elements"][dest_idx]
            else:
                # From previous destination to this one
                prev_idx = optimized_indices[i - 1]
                element = distance_matrix["rows"][prev_idx + 1]["elements"][dest_idx]
            
            if element.get("status") == "OK":
                distance = element["distance"]["value"]  # meters
                duration = element["duration"]["value"]  # seconds
                
                segment = {
                    "from": current_point,
                    "to": dest,
                    "distance_meters": distance,
                    "duration_seconds": duration,
                    "distance_km": round(distance / 1000, 2),
                    "duration_minutes": round(duration / 60, 1),
                    "mode": mode,
                }
                
                route_segments.append(segment)
                total_distance_meters += distance
                total_duration_seconds += duration
                current_point = dest
        
        logger.info(f"Route calculated: {len(route_segments)} segments, {round(total_distance_meters/1000, 2)}km, {round(total_duration_seconds/60, 1)}min")
        
        return {
            "origin": origin,
            "destinations": optimized_destinations,
            "original_order": list(range(len(destinations))),
            "optimized_order": optimized_indices if optimize else None,
            "route_segments": route_segments,
            "total_distance_meters": total_distance_meters,
            "total_distance_km": round(total_distance_meters / 1000, 2),
            "total_duration_seconds": total_duration_seconds,
            "total_duration_minutes": round(total_duration_seconds / 60, 1),
            "mode": mode,
            "optimized": optimize,
            "language": language,
            "source": "google_maps",
        }
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP error calculating route: {str(e)}")
        return {
            "error": True,
            "message": f"HTTP error calculating route: {str(e)}",
        }
    except Exception as e:
        logger.error(f"Error calculating route: {str(e)}")
        return {
            "error": True,
            "message": f"Could not calculate route: {str(e)}",
        }

