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
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from langchain_core.tools import tool
from pydantic import BaseModel

from src.utils.logger import get_logger

logger = get_logger("scoring_tool")


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
    lon_diff = abs(place_location.get("lon", 0) - user_location.get("lon", 0))
    distance = (lat_diff ** 2 + lon_diff ** 2) ** 0.5
    
    # Score: 1.0 for very close, decreases with distance
    # Assume 0.01 degrees ≈ 1km
    distance_km = distance * 111  # Rough conversion
    return max(0, 1.0 - (distance_km * 0.1))


def _score_vibe(place: Dict[str, Any], requirements: Dict[str, Any]) -> float:
    """Score based on vibe/atmosphere match (0-1)."""
    desired_vibe = requirements.get("vibe", "").lower()
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
        return 0.5  # Unknown, neutral score
    
    return 1.0 if open_now else 0.2  # Heavily penalize closed places


def _score_popularity(place: Dict[str, Any], requirements: Dict[str, Any]) -> float:
    """Score based on popularity (review count) (0-1)."""
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


@tool
async def rank_by_score_tool(
    places: List[Dict[str, Any]],
    requirements: Dict[str, Any],
    weights: Optional[Dict[str, float]] = None,
    language: str = "es",
) -> Dict[str, Any]:
    """
    Rank places by multi-factor scoring based on user requirements.
    
    Scoring factors (default weights):
    - Rating (25%): Higher rated places score better
    - Price (15%): Match with user budget
    - Distance (20%): Closer places score better
    - Vibe (15%): Match with desired atmosphere
    - Availability (10%): Open now vs closed
    - Popularity (10%): Number of reviews
    - Preferences (5%): User historical preferences
    
    Args:
        places: List of place objects to rank
        requirements: User requirements (vibe, budget, location, preferences, etc.)
        weights: Optional custom weights for scoring factors (overrides defaults)
        language: Language for explanations ("es" or "en")
    
    Returns:
        Ranked list of places with scores and explanations
    
    Examples:
        - rank_by_score_tool(places, {"budget": "medium", "vibe": "romantic"})
        - rank_by_score_tool(places, {"location": {"lat": 41.65, "lon": -0.89}, "budget": "low"})
    """
    try:
        logger.info(f"Ranking {len(places)} places with custom scoring")
        
        if not places:
            return {
                "ranked_places": [],
                "total_places": 0,
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
        ranked_places = sorted(scored_places, key=lambda x: x["score"], reverse=True)
        
        logger.info(f"Ranking complete. Top score: {ranked_places[0]['score'] if ranked_places else 0}")
        
        return {
            "ranked_places": ranked_places,
            "total_places": len(ranked_places),
            "weights_used": scoring_weights.model_dump(),
            "requirements": requirements,
            "language": language,
        }
        
    except Exception as e:
        logger.error(f"Error ranking places: {str(e)}")
        return {
            "error": True,
            "message": f"Could not rank places: {str(e)}",
        }

