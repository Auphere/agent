"""Plan validation and calculation utilities.

This module provides utilities to validate and enrich plan data:
- Coordinate validation
- Distance calculation using Haversine formula
- Budget estimation
- Travel time calculation
"""

from typing import List, Dict, Any, Optional
from math import radians, sin, cos, sqrt, asin


def validate_stop_coordinates(stop: Dict[str, Any]) -> bool:
    """
    Check if a stop has valid coordinates.
    
    Args:
        stop: Stop dictionary with location data
        
    Returns:
        True if coordinates are valid, False otherwise
    """
    location = stop.get("location", {})
    lat = location.get("lat")
    lng = location.get("lng")
    
    # Check if coordinates exist
    if lat is None or lng is None:
        return False
    
    # Validate coordinate ranges
    try:
        lat_float = float(lat)
        lng_float = float(lng)
        
        if not (-90 <= lat_float <= 90):
            return False
        if not (-180 <= lng_float <= 180):
            return False
            
        return True
    except (ValueError, TypeError):
        return False


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two points using Haversine formula.
    
    This is the most accurate formula for calculating distances on a sphere
    for short to medium distances (< 1000 km). Perfect for city-scale routing.
    
    Args:
        lat1: Latitude of first point in degrees
        lon1: Longitude of first point in degrees
        lat2: Latitude of second point in degrees
        lon2: Longitude of second point in degrees
        
    Returns:
        Distance in kilometers
        
    Reference:
        https://en.wikipedia.org/wiki/Haversine_formula
    """
    # Earth's radius in kilometers
    R = 6371.0
    
    # Convert degrees to radians
    lat1_rad = radians(lat1)
    lon1_rad = radians(lon1)
    lat2_rad = radians(lat2)
    lon2_rad = radians(lon2)
    
    # Haversine formula
    dlat = lat2_rad - lat1_rad
    dlon = lon2_rad - lon1_rad
    
    a = sin(dlat / 2)**2 + cos(lat1_rad) * cos(lat2_rad) * sin(dlon / 2)**2
    c = 2 * asin(sqrt(a))
    
    distance = R * c
    
    return distance


def calculate_route_distance(stops: List[Dict[str, Any]]) -> float:
    """
    Calculate total distance for a route by summing distances between consecutive stops.
    
    Also updates each stop's travelTimeFromPreviousMinutes based on walking speed.
    
    Args:
        stops: List of stop dictionaries with location data
        
    Returns:
        Total route distance in kilometers (rounded to 2 decimals)
    """
    if len(stops) < 2:
        return 0.0
    
    total_distance = 0.0
    WALKING_SPEED_KMH = 5.0  # Average walking speed
    
    for i in range(len(stops) - 1):
        loc1 = stops[i].get("location", {})
        loc2 = stops[i + 1].get("location", {})
        
        lat1 = loc1.get("lat")
        lng1 = loc1.get("lng")
        lat2 = loc2.get("lat")
        lng2 = loc2.get("lng")
        
        # Skip if any coordinate is missing
        if not all([lat1, lng1, lat2, lng2]):
            continue
        
        try:
            # Calculate distance between consecutive stops
            distance = haversine_distance(
                float(lat1), float(lng1),
                float(lat2), float(lng2)
            )
            total_distance += distance
            
            # Calculate and update travel time (walking)
            # Formula: time (hours) = distance (km) / speed (km/h)
            # Convert to minutes and ensure minimum 5 minutes
            travel_time_minutes = int((distance / WALKING_SPEED_KMH) * 60)
            travel_time_minutes = max(5, travel_time_minutes)
            
            # Update the next stop's travel time
            if "location" not in stops[i + 1]:
                stops[i + 1]["location"] = {}
            stops[i + 1]["location"]["travelTimeFromPreviousMinutes"] = travel_time_minutes
            
        except (ValueError, TypeError) as e:
            # Skip invalid coordinates
            continue
    
    return round(total_distance, 2)


def estimate_stop_budget(stops: List[Dict[str, Any]], group_size: int) -> float:
    """
    Estimate budget per person based on stop details and categories.
    
    Uses averageSpendPerPerson from details if available, otherwise estimates
    based on category (restaurant, bar, cafe, etc.).
    
    Args:
        stops: List of stop dictionaries
        group_size: Number of people in the group
        
    Returns:
        Estimated budget per person in euros (rounded to 2 decimals)
    """
    total_per_person = 0.0
    
    # Budget estimates by category (in euros)
    CATEGORY_BUDGETS = {
        "restaurant": 25.0,
        "bar": 15.0,
        "club": 20.0,
        "nightclub": 20.0,
        "cafe": 8.0,
        "coffee": 8.0,
        "activity": 15.0,
        "museum": 12.0,
        "default": 10.0
    }
    
    for stop in stops:
        details = stop.get("details", {})
        avg_spend = details.get("averageSpendPerPerson")
        
        if avg_spend and avg_spend > 0:
            # Use provided budget
            total_per_person += float(avg_spend)
        else:
            # Estimate based on category
            category = stop.get("category", "").lower()
            
            # Find matching category budget
            budget = CATEGORY_BUDGETS.get("default")
            for cat_key, cat_budget in CATEGORY_BUDGETS.items():
                if cat_key in category:
                    budget = cat_budget
                    break
            
            total_per_person += budget
    
    return round(total_per_person, 2)


def validate_plan_data(
    stops: List[Dict[str, Any]],
    total_distance_km: Optional[float] = None,
    budget_per_person: Optional[float] = None,
    group_size: int = 2
) -> Dict[str, Any]:
    """
    Validate and enrich plan data with calculations.
    
    This is the main validation function that:
    1. Validates all stops have coordinates
    2. Calculates distance if not provided
    3. Estimates budget if not provided
    4. Returns validation result with enriched data
    
    Args:
        stops: List of stop dictionaries
        total_distance_km: Optional pre-calculated distance
        budget_per_person: Optional pre-calculated budget
        group_size: Number of people
        
    Returns:
        Dictionary with:
        - valid: bool - whether plan is valid
        - errors: list of error messages
        - warnings: list of warning messages
        - total_distance_km: calculated or provided distance
        - budget_per_person: calculated or provided budget
        - stops: enriched stops with travel times
    """
    errors = []
    warnings = []
    
    # Validate coordinates
    invalid_stops = []
    for i, stop in enumerate(stops):
        if not validate_stop_coordinates(stop):
            stop_name = stop.get("name", f"Stop {i + 1}")
            invalid_stops.append(stop_name)
    
    if invalid_stops:
        errors.append(f"Missing or invalid coordinates for: {', '.join(invalid_stops)}")
    
    # Calculate distance if not provided
    calculated_distance = total_distance_km
    if calculated_distance is None or calculated_distance == 0:
        calculated_distance = calculate_route_distance(stops)
        if calculated_distance > 0:
            warnings.append(f"Distance calculated: {calculated_distance} km")
    
    # Estimate budget if not provided
    calculated_budget = budget_per_person
    if calculated_budget is None or calculated_budget == 0:
        calculated_budget = estimate_stop_budget(stops, group_size)
        if calculated_budget > 0:
            warnings.append(f"Budget estimated: €{calculated_budget}/person")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
        "total_distance_km": calculated_distance,
        "budget_per_person": calculated_budget,
        "stops": stops  # Enriched with travel times
    }
