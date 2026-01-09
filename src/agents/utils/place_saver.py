"""Utility to save places to Rust Places service after extraction."""

from __future__ import annotations

import httpx
from typing import Any, Dict, List, Optional

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger


async def save_places_to_db(
    places: List[Dict[str, Any]],
    settings: Optional[Settings] = None,
    fallback_city: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Save or update places in the Rust Places database.
    
    For each place:
    1. If it has a google_place_id, call the upsert endpoint
    2. Return the saved place with DB ID
    
    Args:
        places: List of normalized place dictionaries
        settings: Optional settings instance
        
    Returns:
        List of places with DB IDs (id field updated from DB)
    """
    if not places:
        return []
    
    settings = settings or get_settings()
    logger = get_logger("place-saver", settings=settings)
    
    # Get Rust Places API URL
    places_api_url = settings.places_api_url.rstrip("/")
    upsert_endpoint = f"{places_api_url}/places/upsert"
    
    # Deduplicate input to avoid repeated upserts and duplicate logs.
    deduped: List[Dict[str, Any]] = []
    seen_google_ids: set[str] = set()
    for place in places:
        google_place_id = place.get("place_id") or place.get("id")
        if not google_place_id:
            deduped.append(place)
            continue
        gid = str(google_place_id)
        if gid in seen_google_ids:
            continue
        seen_google_ids.add(gid)
        deduped.append(place)

    saved_places: List[Dict[str, Any]] = []
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        for place in deduped:
            try:
                # Skip if no google_place_id
                google_place_id = place.get("place_id") or place.get("id")
                if not google_place_id:
                    logger.warning("place-missing-google-id", place_name=place.get("name"))
                    saved_places.append(place)  # Keep original
                    continue
                
                # Prepare request body for upsert
                # Map normalized place to CreatePlaceRequest format
                location = place.get("location", {})
                lat = location.get("lat") or location.get("latitude", 0.0)
                lon = location.get("lon") or location.get("lng") or location.get("longitude", 0.0)
                
                # Map category to type (must match DB constraint: restaurant, bar, cafe, club, nightclub, pub, lounge, bistro, other)
                category = place.get("category", "restaurant")
                type_mapping = {
                    "restaurant": "restaurant",
                    "bar": "bar",
                    "club": "nightclub",  # Use 'nightclub' not 'night_club'
                    "cafe": "cafe",
                    "lounge": "lounge",
                    "activity": "other",  # Activities map to 'other'
                    "place": "other",  # Generic places map to 'other'
                }
                place_type = type_mapping.get(category, "restaurant")  # Default to 'restaurant' not 'place'
                
                # Extract main categories
                main_categories = [category]
                if place.get("vibe"):
                    main_categories.extend(place["vibe"][:2])
                
                # Extract city and district from multiple possible shapes.
                address = place.get("address", "") or ""
                neighborhood = place.get("neighborhood")

                # Places service search responses may store city/district under customAttributes.
                custom_attrs = place.get("customAttributes") or place.get("custom_attributes") or {}
                city = (
                    place.get("city")
                    or (custom_attrs.get("city") if isinstance(custom_attrs, dict) else None)
                    or fallback_city
                )

                # Best-effort parse city from address if still missing
                if not city and address:
                    parts = [p.strip() for p in address.split(",") if p.strip()]
                    if parts:
                        # Common formats: "... , Zaragoza, España" or "... , 50001 Zaragoza, España"
                        candidate = parts[-2] if len(parts) >= 2 else parts[-1]
                        token = candidate.split()[-1] if candidate.split() else None
                        if token and token.isalpha():
                            city = token

                district = (
                    neighborhood
                    or (custom_attrs.get("district") if isinstance(custom_attrs, dict) else None)
                )
                if not district and address:
                    parts = [p.strip() for p in address.split(",") if p.strip()]
                    if len(parts) >= 3:
                        district = parts[2]

                # City is required by auphere-places CreatePlaceRequest. If we can't determine it,
                # skip saving to DB to avoid corrupting data.
                if not city:
                    logger.warning(
                        "place-save-skipped-missing-city",
                        place_name=place.get("name"),
                        google_id=google_place_id,
                    )
                    saved_places.append(place)
                    continue
                
                # Build request
                request_body = {
                    "name": place.get("name", ""),
                    "description": place.get("description"),
                    "type": place_type,
                    "location": [lon, lat],  # [longitude, latitude]
                    "address": address,
                    "city": str(city),
                    "district": district,
                    "phone": place.get("phone"),
                    "website": place.get("website"),
                    "google_place_id": str(google_place_id),
                    "google_rating": place.get("rating"),
                    "google_rating_count": place.get("reviewCount"),
                    "price_level": place.get("priceLevel"),
                    "main_categories": main_categories,
                    "secondary_categories": [],
                    "cuisine_types": [],
                    "is_open_now": place.get("openNow"),
                    "suitable_for": [],
                }
                
                # Call upsert endpoint
                response = await client.post(upsert_endpoint, json=request_body)
                response.raise_for_status()
                
                saved_place = response.json()
                
                # Update place with DB ID (UUID from Rust service)
                db_id = saved_place.get("id")
                if db_id:
                    place["id"] = str(db_id)  # Use DB UUID as primary ID
                    place["db_id"] = str(db_id)  # Keep DB ID separate for reference
                    # Keep google_place_id in place_id field
                    if not place.get("place_id"):
                        place["place_id"] = str(google_place_id)
                
                logger.info(
                    "place-saved-to-db",
                    place_name=place.get("name"),
                    db_id=place.get("id"),
                    google_id=google_place_id,
                )
                
                saved_places.append(place)
                
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "place-save-failed-http",
                    place_name=place.get("name"),
                    status=exc.response.status_code,
                    error=exc.response.text,
                )
                saved_places.append(place)  # Keep original on error
            except Exception as exc:
                logger.error(
                    "place-save-failed",
                    place_name=place.get("name"),
                    error=str(exc),
                )
                saved_places.append(place)  # Keep original on error
    
    return saved_places

