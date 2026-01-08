"""
Scoring tool for ranking places by custom requirements.

Multi-factor scoring algorithm that considers:
- Rating and reviews
- Price level vs budget
- Distance from location
- Vibe/atmosphere match
- Availability/open status
- Popularity
- User preferences

Enhanced with:
- Dynamic result count selection based on quality threshold
- User-requested count respect
- Hard limits (min 3, max 10) for response consistency
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool
from pydantic import BaseModel

from src.utils.logger import get_logger

logger = get_logger("scoring_tool")

# ============================================================================
# Constants for dynamic count selection
# ============================================================================

MIN_RESULTS = 3  # Minimum places to return (unless fewer available)
MAX_RESULTS = 10  # Maximum places to return (to avoid heavy responses)
DEFAULT_RESULTS = 5  # Default when user doesn't specify
QUALITY_THRESHOLD = 0.5  # Minimum score to include a place


class ScoringWeights(BaseModel):
    """Default weights for scoring factors."""
    
    rating: float = 0.25
    price: float = 0.15
    distance: float = 0.20
    vibe: float = 0.15
    availability: float = 0.10
    popularity: float = 0.10
    preferences: float = 0.05


def _score_rating(place: Dict[str, Any], requirements: Dict[str, Any]) -> float:
    """Score based on rating (0-1)."""
    rating = place.get("rating", 0)
    if rating == 0:
        return 0.5  # Unknown rating, neutral score
    
    # Normalize to 0-1 (rating is typically 0-5)
    return min(rating / 5.0, 1.0)


def _score_price(place: Dict[str, Any], requirements: Dict[str, Any]) -> float:
    """Score based on price match with budget (0-1)."""
    price_level = place.get("priceLevel")
    if price_level is None:
        price_level = place.get("price_level")
    budget = requirements.get("budget", "medium")
    
    # Map budget to price level (1-4)
    budget_map = {
        "low": 1,
        "economic": 1,
        "economico": 1,
        "medium": 2,
        "medio": 2,
        "high": 3,
        "alto": 3,
        "luxury": 4,
        "lujo": 4,
    }
    
    if price_level is None:
        return 0.5  # Unknown price, neutral score
    
    target_price = budget_map.get(budget.lower(), 2)
    difference = abs(price_level - target_price)
    
    # Score: 1.0 for exact match, decreases with difference
    return max(0, 1.0 - (difference * 0.3))


def _score_distance(place: Dict[str, Any], requirements: Dict[str, Any]) -> float:
    """Score based on distance (0-1, closer is better)."""
    user_location = requirements.get("location")
    if not user_location:
        return 0.5  # No location, neutral score
    
    place_location = place.get("location", {})
    if not place_location:
        return 0.5
    
    # Simple distance calculation (not accurate, but good enough for ranking)
    lat_diff = abs(place_location.get("lat", 0) - user_location.get("lat", 0))
    lon_val = place_location.get("lon", place_location.get("lng", 0))
    lon_diff = abs(lon_val - user_location.get("lon", user_location.get("lng", 0)))
    distance = (lat_diff ** 2 + lon_diff ** 2) ** 0.5
    
    # Score: 1.0 for very close, decreases with distance
    # Assume 0.01 degrees ≈ 1km
    distance_km = distance * 111  # Rough conversion
    return max(0, 1.0 - (distance_km * 0.1))


def _score_vibe(place: Dict[str, Any], requirements: Dict[str, Any]) -> float:
    """Score based on vibe/atmosphere match (0-1)."""
    desired_vibe = (requirements.get("vibe") or "").strip().lower()
    if not desired_vibe and isinstance(requirements.get("vibes"), list):
        # Accept plan-style requirements where vibes is a list.
        desired_vibe = str((requirements.get("vibes") or [""])[0]).strip().lower()
    if not desired_vibe:
        return 0.5  # No vibe preference, neutral score
    
    # Check place types/categories
    place_types = place.get("types", [])
    place_name = place.get("name", "").lower()
    place_description = place.get("description", "").lower()
    
    # Vibe matching keywords
    vibe_keywords = {
        "romantic": ["romantic", "romántico", "intimate", "íntimo", "cozy", "acogedor"],
        "romantico": ["romantic", "romántico", "intimate", "íntimo", "cozy", "acogedor"],
        "party": ["party", "fiesta", "club", "discoteca", "lively", "animado"],
        "fiesta": ["party", "fiesta", "club", "discoteca", "lively", "animado"],
        "quiet": ["quiet", "tranquilo", "peaceful", "calm", "sereno"],
        "tranquilo": ["quiet", "tranquilo", "peaceful", "calm", "sereno"],
        "family": ["family", "familiar", "kids", "niños", "children"],
        "familiar": ["family", "familiar", "kids", "niños", "children"],
        "trendy": ["trendy", "moderno", "hip", "modern", "contemporary"],
        "moderno": ["trendy", "moderno", "hip", "modern", "contemporary"],
    }
    
    keywords = vibe_keywords.get(desired_vibe, [desired_vibe])
    
    # Check for keyword matches
    matches = 0
    for keyword in keywords:
        if keyword in place_name or keyword in place_description:
            matches += 1
        for ptype in place_types:
            if keyword in ptype.lower():
                matches += 1
    
    return min(matches * 0.3, 1.0)


def _score_availability(place: Dict[str, Any], requirements: Dict[str, Any]) -> float:
    """Score based on availability (0-1)."""
    open_now = place.get("open_now")
    if open_now is None:
        open_now = place.get("is_open")
    
    if open_now is None:
        return 0.5  # Unknown, neutral score
    
    return 1.0 if open_now else 0.2  # Heavily penalize closed places


def _score_popularity(place: Dict[str, Any], requirements: Dict[str, Any]) -> float:
    """Score based on popularity (review count) (0-1)."""
    review_count = place.get("reviewCount")
    if review_count is None:
        review_count = place.get("review_count")
    if review_count is None:
        review_count = place.get("user_ratings_total", 0)
    
    # Score based on review count (logarithmic scale)
    if review_count == 0:
        return 0.3  # New place, lower score
    elif review_count < 10:
        return 0.5
    elif review_count < 50:
        return 0.7
    elif review_count < 200:
        return 0.85
    else:
        return 1.0


# ============================================================================
# Dynamic Count Selection
# ============================================================================

def extract_requested_count(query: str) -> Optional[int]:
    """
    Extract user-requested count from query text.
    
    Examples:
        - "dame 2 opciones" -> 2
        - "recomiendame 3 bares" -> 3
        - "top 5 restaurantes" -> 5
        - "muéstrame restaurantes" -> None (no specific count)
    
    Args:
        query: User query text
        
    Returns:
        Requested count or None if not specified
    """
    query_lower = query.lower()
    
    # Patterns to match explicit count requests
    patterns = [
        r"(\d+)\s*(?:opciones?|options?)",  # "2 opciones", "3 options"
        r"(\d+)\s*(?:lugares?|places?|sitios?|spots?)",  # "5 lugares"
        r"(\d+)\s*(?:restaurantes?|bares?|cafes?|clubs?)",  # "3 restaurantes"
        r"(?:dame|give me|show me|muéstrame|recomiéndame|recommend)\s*(\d+)",  # "dame 2"
        r"(?:top|mejores?|best)\s*(\d+)",  # "top 5", "mejores 3"
        r"(\d+)\s*(?:recomendaciones?|recommendations?)",  # "5 recomendaciones"
    ]
    
    for pattern in patterns:
        match = re.search(pattern, query_lower)
        if match:
            try:
                count = int(match.group(1))
                # Validate reasonable range
                if 1 <= count <= MAX_RESULTS:
                    return count
            except (ValueError, IndexError):
                continue
    
    return None


def determine_optimal_count(
    ranked_places: List[Dict[str, Any]],
    user_requested: Optional[int] = None,
    quality_threshold: float = QUALITY_THRESHOLD,
) -> int:
    """
    Determine how many places to return based on multiple factors.
    
    Priority:
    1. User explicit request (e.g., "2 opciones") - respected up to MAX_RESULTS
    2. Score distribution - only include places above quality threshold
    3. Hard limits: min=MIN_RESULTS, max=MAX_RESULTS
    
    Args:
        ranked_places: List of scored places (each has 'score' key)
        user_requested: Number explicitly requested by user (or None)
        quality_threshold: Minimum score to include a place
        
    Returns:
        Optimal number of places to return
    """
    total_available = len(ranked_places)
    
    if total_available == 0:
        return 0
    
    # 1. If user requested specific count, respect it (capped at MAX_RESULTS)
    if user_requested is not None:
        return min(user_requested, total_available, MAX_RESULTS)
    
    # 2. Count places above quality threshold
    quality_places = sum(
        1 for p in ranked_places 
        if p.get("score", 0) >= quality_threshold
    )
    
    # 3. Apply hard limits
    # If we have many quality places, return up to DEFAULT_RESULTS
    # If few quality places, return at least MIN_RESULTS (if available)
    if quality_places >= DEFAULT_RESULTS:
        return min(DEFAULT_RESULTS, total_available, MAX_RESULTS)
    elif quality_places >= MIN_RESULTS:
        return quality_places
    else:
        # Return what we have, up to MIN_RESULTS
        return min(MIN_RESULTS, total_available)


def select_top_places(
    ranked_places: List[Dict[str, Any]],
    count: int,
) -> Tuple[List[Dict[str, Any]], int]:
    """
    Select top N places from ranked list.
    
    Args:
        ranked_places: Full list of ranked places
        count: Number to select
        
    Returns:
        Tuple of (selected_places, actual_count)
    """
    selected = ranked_places[:count]
    return selected, len(selected)


@tool
async def rank_by_score_tool(
    places: Optional[List[Dict[str, Any]]] = None,
    requirements: Optional[Dict[str, Any]] = None,
    weights: Optional[Dict[str, float]] = None,
    language: str = "es",
    user_query: Optional[str] = None,
    requested_count: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Rank places by multi-factor scoring and return optimal number of results.
    
    Scoring factors (default weights):
    - Rating (25%): Higher rated places score better
    - Price (15%): Match with user budget
    - Distance (20%): Closer places score better
    - Vibe (15%): Match with desired atmosphere
    - Availability (10%): Open now vs closed
    - Popularity (10%): Number of reviews
    
    Dynamic Count Selection:
    - If user requests specific count (e.g., "2 opciones"), respects it
    - Otherwise, returns quality-filtered results (score > 0.5)
    - Hard limits: min 3, max 10 places
    
    Args:
        places: List of place objects to rank
        requirements: User requirements (vibe, budget, location, preferences, etc.)
        weights: Optional custom weights for scoring factors (overrides defaults)
        language: Language for explanations ("es" or "en")
        user_query: Original user query (to extract requested count)
        requested_count: Explicit count override (if already extracted)
    
    Returns:
        Ranked and filtered list of places with scores
        - ranked_places: The selected top places (already limited)
        - actual_count: EXACT number of places returned (use this in response!)
        - total_scored: Total places that were scored (before filtering)
    
    Examples:
        - rank_by_score_tool(places, {"budget": "medium"}, user_query="dame 2 opciones")
        - rank_by_score_tool(places, {"vibe": "romantic"}, requested_count=5)
    """
    try:
        if places is None or requirements is None:
            return {
                "error": True,
                "message": (
                    "Missing required inputs. Please call rank_by_score_tool again with BOTH "
                    "`places` (list of place objects from places_search_tool) and "
                    "`requirements` (dict with budget/vibe/location)."
                ),
                "expected": {
                    "places": "[PlaceNormalized, ...]",
                    "requirements": {"budget": "low|medium|high", "vibe": "string", "location": {"lat": 0, "lon": 0}},
                    "user_query": "original query to extract count (optional)",
                    "requested_count": "explicit count override (optional)",
                },
                "ranked_places": [],
                "actual_count": 0,
                "total_scored": 0,
            }

        logger.info(f"Ranking {len(places)} places with dynamic count selection")
        
        if not places:
            return {
                "ranked_places": [],
                "actual_count": 0,
                "total_scored": 0,
                "message": "No places to rank.",
            }
        
        # Initialize weights
        if weights:
            scoring_weights = ScoringWeights(**weights)
        else:
            scoring_weights = ScoringWeights()
        
        # Score each place
        scored_places = []
        for place in places:
            scores = {
                "rating": _score_rating(place, requirements),
                "price": _score_price(place, requirements),
                "distance": _score_distance(place, requirements),
                "vibe": _score_vibe(place, requirements),
                "availability": _score_availability(place, requirements),
                "popularity": _score_popularity(place, requirements),
            }
            
            # Calculate weighted total score
            total_score = (
                scores["rating"] * scoring_weights.rating +
                scores["price"] * scoring_weights.price +
                scores["distance"] * scoring_weights.distance +
                scores["vibe"] * scoring_weights.vibe +
                scores["availability"] * scoring_weights.availability +
                scores["popularity"] * scoring_weights.popularity
            )
            
            # Round to 2 decimals
            total_score = round(total_score, 2)
            
            scored_places.append({
                "place": place,
                "score": total_score,
                "score_breakdown": {k: round(v, 2) for k, v in scores.items()},
            })
        
        # Sort by score (descending)
        all_ranked = sorted(scored_places, key=lambda x: x["score"], reverse=True)
        total_scored = len(all_ranked)
        
        # Determine optimal count
        user_count = requested_count
        if user_count is None and user_query:
            user_count = extract_requested_count(user_query)
        
        optimal_count = determine_optimal_count(all_ranked, user_count)
        
        # Select top places
        selected_places, actual_count = select_top_places(all_ranked, optimal_count)
        
        logger.info(
            f"Ranking complete. Scored: {total_scored}, Returning: {actual_count}, "
            f"Top score: {selected_places[0]['score'] if selected_places else 0}"
        )
        
        return {
            "ranked_places": selected_places,
            "actual_count": actual_count,  # CRITICAL: Use this in response text!
            "total_scored": total_scored,
            "user_requested_count": user_count,
            "weights_used": scoring_weights.model_dump(),
            "requirements": requirements,
            "language": language,
        }
        
    except Exception as e:
        logger.error(f"Error ranking places: {str(e)}")
        return {
            "error": True,
            "message": f"Could not rank places: {str(e)}",
            "ranked_places": [],
            "actual_count": 0,
        }

