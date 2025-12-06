"""Normalize place data to ensure consistent structure across all sources."""

from __future__ import annotations

from typing import Any, Dict, List, Optional


def normalize_place(raw_place: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize a single place to consistent format for frontend consumption.
    
    Frontend expects:
    - id (string)
    - name (string)
    - category (string): restaurant, bar, club, cafe, activity, lounge
    - description (optional)
    - vibe (list of strings, optional)
    - crowdLevel (optional)
    - musicType (optional)
    - priceLevel (number 1-4)
    - rating (number)
    - reviewCount (number)
    - address (string)
    - neighborhood (string)
    - distance (optional)
    - openNow (boolean)
    - images (list of strings)
    - location (object with lat, lon)
    - currentStatus (optional)
    """
    if not raw_place or not raw_place.get("name"):
        return None
    
    # Extract ID
    place_id = (
        raw_place.get("id") or 
        raw_place.get("place_id") or 
        raw_place.get("_id") or
        ""
    )
    
    # Extract name
    name = raw_place.get("name", "")
    
    # Extract category/type
    category = raw_place.get("category") or raw_place.get("type")
    if not category:
        # Try to infer from main_categories
        main_categories = raw_place.get("main_categories", [])
        if main_categories:
            category = _map_type_to_category(main_categories[0])
        else:
            category = "place"
    else:
        category = _map_type_to_category(category)
    
    # Extract rating
    rating = (
        raw_place.get("rating") or
        raw_place.get("google_rating") or
        0
    )
    
    # Extract review count
    review_count = (
        raw_place.get("reviewCount") or
        raw_place.get("google_rating_count") or
        raw_place.get("user_ratings_total") or
        0
    )
    
    # Extract address/neighborhood
    address = raw_place.get("address") or ""
    neighborhood = (
        raw_place.get("neighborhood") or
        raw_place.get("district") or
        raw_place.get("city") or
        "Zaragoza"
    )
    
    # Extract price level
    price_level = raw_place.get("priceLevel") or raw_place.get("price_level") or 2
    if not isinstance(price_level, int) or price_level < 1:
        price_level = 2
    elif price_level > 4:
        price_level = 4
    
    # Extract images
    images = []
    if raw_place.get("images"):
        images = raw_place["images"] if isinstance(raw_place["images"], list) else [raw_place["images"]]
    elif raw_place.get("photo_url"):
        images = [raw_place["photo_url"]]
    elif raw_place.get("primary_photo_url"):
        images = [raw_place["primary_photo_url"]]
    elif raw_place.get("primary_photo_thumbnail_url"):
        images = [raw_place["primary_photo_thumbnail_url"]]
    
    # Extract location
    location = None
    if raw_place.get("location"):
        loc = raw_place["location"]
        if isinstance(loc, list) and len(loc) >= 2:
            # Format: [longitude, latitude] (GeoJSON standard)
            location = {
                "lon": loc[0],
                "lat": loc[1],
                "lng": loc[0],  # Alias
            }
        elif isinstance(loc, dict):
            lat = loc.get("lat") or loc.get("latitude")
            lon = loc.get("lon") or loc.get("lng") or loc.get("longitude")
            if lat and lon:
                location = {
                    "lat": lat,
                    "lon": lon,
                    "lng": lon,
                }
    
    # Extract vibe
    vibe = []
    if raw_place.get("vibe"):
        if isinstance(raw_place["vibe"], list):
            vibe = raw_place["vibe"]
        else:
            vibe = [raw_place["vibe"]]
    elif raw_place.get("vibe_descriptor"):
        vibe_desc = raw_place["vibe_descriptor"]
        if isinstance(vibe_desc, dict):
            # Extract vibe from descriptor object
            vibe = list(vibe_desc.keys())[:3]  # Take top 3
        elif isinstance(vibe_desc, list):
            vibe = vibe_desc[:3]
    
    # Extract crowd level (default to moderate)
    crowd_level = raw_place.get("crowdLevel") or raw_place.get("crowd_level") or "moderate"
    
    # Extract music type (default to ambient)
    music_type = raw_place.get("musicType") or raw_place.get("music_type") or "ambient"
    
    # Extract open now (default to true)
    open_now = raw_place.get("openNow")
    if open_now is None:
        open_now = raw_place.get("open_now")
    if open_now is None:
        open_now = True
    
    # Extract description
    description = raw_place.get("description") or raw_place.get("summary") or ""
    
    # Extract current status
    current_status = raw_place.get("currentStatus") or raw_place.get("current_status")
    
    # Build normalized place
    normalized = {
        "id": str(place_id),
        "place_id": str(place_id),
        "name": name,
        "category": category,
        "description": description,
        "vibe": vibe,
        "crowdLevel": crowd_level,
        "musicType": music_type,
        "priceLevel": price_level,
        "rating": float(rating) if rating else 0,
        "reviewCount": int(review_count) if review_count else 0,
        "address": address,
        "neighborhood": neighborhood,
        "openNow": bool(open_now),
        "images": images,
        "location": location,
    }
    
    # Add optional fields if present
    if current_status:
        normalized["currentStatus"] = current_status
    
    if raw_place.get("distance"):
        normalized["distance"] = raw_place["distance"]
    
    # Remove None values
    return {k: v for k, v in normalized.items() if v is not None}


def normalize_places(raw_places: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Normalize a list of places."""
    if not raw_places:
        return []
    
    normalized = []
    for place in raw_places:
        norm = normalize_place(place)
        if norm and norm.get("name"):
            normalized.append(norm)
    
    return normalized


def _map_type_to_category(place_type: str) -> str:
    """Map various place types to frontend categories."""
    if not place_type:
        return "place"
    
    type_lower = place_type.lower()
    
    if any(t in type_lower for t in ["restaurant", "food", "meal", "dining", "comida"]):
        return "restaurant"
    elif any(t in type_lower for t in ["bar", "pub", "tavern", "cerveceria"]):
        return "bar"
    elif any(t in type_lower for t in ["night_club", "club", "disco", "discoteca"]):
        return "club"
    elif any(t in type_lower for t in ["cafe", "coffee", "cafeteria"]):
        return "cafe"
    elif any(t in type_lower for t in ["lounge", "cocktail"]):
        return "lounge"
    else:
        return "activity"

