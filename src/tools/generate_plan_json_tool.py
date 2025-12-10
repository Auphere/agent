"""Tool for generating structured plan JSON for frontend rendering."""

from typing import Any, Dict, List, Optional
from uuid import uuid4
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.logger import get_logger

logger = get_logger("generate_plan_json_tool")


class PlanStop(BaseModel):
    """A single stop in the plan."""
    stopNumber: int = Field(description="Stop number in sequence (1, 2, 3, ...)")
    localId: str = Field(description="Local place ID")
    name: str = Field(description="Place name")
    category: str = Field(description="Category: restaurant, bar, club, cafe, activity")
    typeLabel: Optional[str] = Field(None, description="Type label like 'Italian restaurant', 'Jazz bar'")
    timing: Dict[str, Any] = Field(description="Timing info with recommendedStart, suggestedDurationMinutes, estimatedEnd")
    location: Dict[str, Any] = Field(description="Location with address, lat, lng, travelTimeFromPreviousMinutes")
    details: Dict[str, Any] = Field(description="Details with vibes, targetAudience, music, noiseLevel, averageSpendPerPerson")
    selectionReasons: List[str] = Field(description="Why this place was selected")
    actions: Dict[str, Any] = Field(description="Actions with canReserve, reservationUrl, googleMapsUrl, phone")
    alternatives: Optional[List[Dict[str, Any]]] = Field(None, description="Alternative places")
    personalTips: Optional[List[str]] = Field(None, description="Personal tips")


@tool
async def generate_plan_json_tool(
    title: str,
    description: str,
    category: str,
    vibes: List[str],
    date: str,
    start_time: str,
    city: str,
    group_size: int,
    stops: List[Dict[str, Any]],
    total_duration_hours: float,
    total_distance_km: Optional[float] = None,
    budget_per_person: Optional[float] = None,
    final_recommendations: Optional[List[str]] = None
) -> Dict[str, Any]:
    """
    Generate a structured plan JSON for frontend rendering.
    
    This tool creates a complete plan object that the frontend can display
    with a timeline, map, and all necessary details for each stop.
    
    Args:
        title: Plan title (e.g., "Romantic Evening in Madrid")
        description: Brief description
        category: Plan category (romantic, friends, family, etc.)
        vibes: List of vibes (romantic, energetic, chill, etc.)
        date: Execution date (YYYY-MM-DD)
        start_time: Start time (HH:MM)
        city: City name
        group_size: Number of people
        stops: List of stop objects with all required fields
        total_duration_hours: Total duration in hours
        total_distance_km: Total distance in km
        budget_per_person: Estimated budget per person
        final_recommendations: Final tips and recommendations
    
    Returns:
        Complete structured plan JSON
    """
    try:
        logger.info(f"Generating plan JSON: {title}")
        
        plan_id = str(uuid4())
        
        # Build execution metadata
        execution = {
            "date": date,
            "startTime": start_time,
            "durationHours": total_duration_hours,
            "city": city,
            "zones": list(set(stop.get("location", {}).get("zone", "") for stop in stops if stop.get("location", {}).get("zone"))),
            "groupSize": group_size,
            "groupComposition": "couple" if group_size == 2 and "romantic" in vibes else "friends"
        }
        
        # Build summary
        total_budget = (budget_per_person * group_size) if budget_per_person else 0
        summary = {
            "totalDuration": f"{int(total_duration_hours)}h {int((total_duration_hours % 1) * 60)}m",
            "totalDistanceKm": total_distance_km,
            "budget": {
                "total": total_budget,
                "perPerson": budget_per_person or 0,
                "withinBudget": True,
                "breakdown": {}
            },
            "metrics": {
                "vibeMatchPercent": 95,
                "averageVenueRating": sum(stop.get("rating", 0) for stop in stops) / len(stops) if stops else 0,
                "successProbabilityLabel": "High"
            }
        }
        
        # Generate tags from vibes and category
        tags = vibes + [category, city.lower(), f"{group_size}people"]
        
        plan_json = {
            "planId": plan_id,
            "title": title,
            "description": description,
            "category": category,
            "vibes": vibes,
            "tags": tags,
            "execution": execution,
            "stops": stops,
            "summary": summary,
            "finalRecommendations": final_recommendations or []
        }
        
        logger.info(f"Plan JSON generated successfully with {len(stops)} stops")
        
        return {
            "success": True,
            "plan": plan_json,
            "message": f"Generated plan '{title}' with {len(stops)} stops"
        }
        
    except Exception as e:
        logger.error(f"Error generating plan JSON: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to generate structured plan"
        }

