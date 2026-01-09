"""
Tool for generating structured plan JSON for frontend rendering.

IMPROVEMENTS OVER ORIGINAL:
1. ✅ Budget validation against user limits
2. ✅ Proper handling of TBD values
3. ✅ Better error handling for missing coordinates
4. ✅ Calculation of travel times between stops
5. ✅ Budget warnings when exceeding user limits
6. ✅ Division by zero protection
"""

from typing import Any, Dict, List, Optional
from uuid import uuid4
import json

from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.utils.logger import get_logger
from src.utils.plan_validator import validate_plan_data

logger = get_logger("generate_plan_json_tool")


class PlanStop(BaseModel):
    """A single stop in the plan."""

    stopNumber: int = Field(description="Stop number in sequence (1, 2, 3, ...)")
    localId: str = Field(description="Local place ID")
    name: str = Field(description="Place name")
    category: str = Field(description="Category: restaurant, bar, club, cafe, activity")
    typeLabel: Optional[str] = Field(None, description="Type label like 'Italian restaurant', 'Jazz bar'")
    timing: Dict[str, Any] = Field(
        description="Timing info with recommendedStart, suggestedDurationMinutes, estimatedEnd"
    )
    location: Dict[str, Any] = Field(
        description="Location with address, lat, lng, travelTimeFromPreviousMinutes"
    )
    details: Dict[str, Any] = Field(
        description="Details with vibes, targetAudience, music, noiseLevel, averageSpendPerPerson"
    )
    selectionReasons: List[str] = Field(description="Why this place was selected")
    actions: Dict[str, Any] = Field(
        description="Actions with canReserve, reservationUrl, googleMapsUrl, phone"
    )
    alternatives: Optional[List[Dict[str, Any]]] = Field(None, description="Alternative places")
    personalTips: Optional[List[str]] = Field(None, description="Personal tips")
    images: Optional[List[Dict[str, Any]]] = Field(None, description="Images from Google Places")


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
    user_max_budget_per_person: Optional[float] = None,
    final_recommendations: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    Generate a structured plan JSON for frontend rendering.

    This tool creates a complete plan object that the frontend can display
    with a timeline, map, and all necessary details for each stop.

    CRITICAL: The 'stops' parameter is REQUIRED and must be a non-empty list.
    Each stop must be built from the places found in previous steps.

    Args:
        title: Plan title (e.g., "Romantic Evening in Madrid")
        description: Brief description of the plan
        category: Plan category (romantic, friends, family, etc.)
        vibes: List of vibes (romantic, energetic, chill, etc.)
        date: Execution date (YYYY-MM-DD or "TBD" if not specified)
        start_time: Start time (HH:MM or "TBD" if not specified)
        city: City name where the plan takes place
        group_size: Number of people in the group
        stops: REQUIRED - List of stop objects. Each stop MUST include:
            - stopNumber: int (1, 2, 3...)
            - localId: str (place ID from search results)
            - name: str (place name)
            - category: str (restaurant, bar, club, cafe, activity)
            - timing: dict with recommendedStart, suggestedDurationMinutes
            - location: dict with address, lat, lng
            - details: dict with vibes, averageSpendPerPerson
            - selectionReasons: list of strings explaining why selected
            - actions: dict with googleMapsUrl
            Example: [{"stopNumber": 1, "localId": "abc123", "name": "Cafe Example", ...}]
        total_duration_hours: Total duration in hours
        total_distance_km: Total distance in km (optional, will be calculated)
        budget_per_person: Estimated budget per person (optional)
        user_max_budget_per_person: User's max budget for validation (optional)
        final_recommendations: Final tips and recommendations (optional)

    Returns:
        Complete structured plan JSON with validation, or error if stops is empty/missing
    """

    try:
        # ✅ CRITICAL: Validate stops is not empty
        if not stops or len(stops) == 0:
            logger.error("generate_plan_json_tool called without stops")
            return {
                "success": False,
                "error": "No stops provided",
                "message": "Cannot generate a plan without stops. Please search for places first and build the stops list from the search results.",
            }

        # ✅ NEW: Validate city - don't accept TBD
        if city == "TBD" or not city:
            # Try to extract city from stops addresses
            for stop in stops:
                address = stop.get("location", {}).get("address", "")
                if address:
                    # Try to extract city from address (usually second to last part)
                    parts = address.split(",")
                    if len(parts) >= 2:
                        city = parts[-2].strip()
                        break

            if city == "TBD" or not city:
                city = "Ciudad"  # Better fallback than TBD

        # Clean up title if it contains TBD
        if "TBD" in title:
            title = title.replace(" en TBD", "").replace(" TBD", "")

        logger.info(f"Generating plan JSON: {title}")

        plan_id = str(uuid4())

        # VALIDATE AND ENRICH PLAN DATA
        # This ensures all stops have coordinates and calculates missing metrics
        validation_result = validate_plan_data(
            stops=stops,
            total_distance_km=total_distance_km,
            budget_per_person=budget_per_person,
            group_size=group_size,
        )

        # Check if plan is valid (all stops have coordinates)
        if not validation_result["valid"]:
            error_msg = "; ".join(validation_result["errors"])
            logger.error(f"Plan validation failed: {error_msg}")
            return {
                "success": False,
                "error": "Invalid plan data",
                "message": f"Cannot generate plan: {error_msg}",
                "details": validation_result["errors"],
            }

        # Log warnings (e.g., calculated distance/budget)
        for warning in validation_result["warnings"]:
            logger.info(f"Plan enrichment: {warning}")

        # Use validated/enriched data
        enriched_stops = validation_result["stops"]
        calculated_distance = validation_result["total_distance_km"]
        calculated_budget = validation_result["budget_per_person"]

        # ✅ NEW: BUDGET VALIDATION
        budget_exceeded = False
        budget_warning = None
        if user_max_budget_per_person and calculated_budget:
            # Allow 10% tolerance
            if calculated_budget > user_max_budget_per_person * 1.1:
                budget_exceeded = True
                budget_warning = (
                    f"⚠️ El presupuesto estimado (€{calculated_budget:.0f}/persona) "
                    f"excede tu límite (€{user_max_budget_per_person:.0f}/persona). "
                    f"Considera ajustar el plan o aumentar el presupuesto."
                )
                logger.warning(f"Budget exceeded: {budget_warning}")

                # Add warning to final recommendations
                if not final_recommendations:
                    final_recommendations = []
                if budget_warning not in final_recommendations:
                    final_recommendations.insert(0, budget_warning)

        # Build execution metadata
        execution = {
            "date": date if date != "TBD" else None,  # ✅ Convert TBD to None
            "startTime": start_time if start_time != "TBD" else None,  # ✅ Convert TBD to None
            "durationHours": total_duration_hours,
            "city": city,
            "zones": list(
                set(
                    stop.get("location", {}).get("zone", "")
                    for stop in enriched_stops
                    if stop.get("location", {}).get("zone")
                )
            ),
            "groupSize": group_size,
            "groupComposition": "couple" if group_size == 2 and "romantic" in vibes else "friends",
        }

        # Build summary with VALIDATED/CALCULATED data
        total_budget = (calculated_budget * group_size) if calculated_budget else 0

        # ✅ NEW: Protected average rating calculation (avoid division by zero)
        average_rating = (
            sum(stop.get("details", {}).get("rating") or 0 for stop in enriched_stops) / len(enriched_stops)
            if enriched_stops
            else 0
        )

        summary = {
            "totalDuration": f"{int(total_duration_hours)}h {int((total_duration_hours % 1) * 60)}m",
            "totalDistanceKm": calculated_distance,
            "budget": {
                "total": total_budget,
                "perPerson": calculated_budget,
                "withinBudget": not budget_exceeded,  # ✅ FALSE if exceeds
                "userMaxBudget": user_max_budget_per_person,  # ✅ NEW
                "exceedsBy": (
                    calculated_budget - user_max_budget_per_person
                    if budget_exceeded and user_max_budget_per_person
                    else 0
                ),
                "breakdown": {},
            },
            "metrics": {
                "vibeMatchPercent": 95,
                "averageVenueRating": round(average_rating, 1),
                "successProbabilityLabel": "High" if not budget_exceeded else "Medium",
            },
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
            "stops": enriched_stops,  # Use enriched stops with travel times
            "summary": summary,
            "finalRecommendations": final_recommendations or [],
        }

        logger.info(
            f"Plan JSON generated successfully: {len(enriched_stops)} stops, "
            f"{calculated_distance}km, €{calculated_budget:.0f}/person, "
            f"withinBudget={not budget_exceeded}"
        )

        return {
            "success": True,
            "plan": plan_json,
            "message": f"Generated plan '{title}' with {len(stops)} stops",
            "budget_exceeded": budget_exceeded,
        }

    except Exception as e:
        logger.error(f"Error generating plan JSON: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to generate structured plan",
        }
