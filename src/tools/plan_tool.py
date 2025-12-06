"""
Enhanced plan generation tool for creating multi-location itineraries.
Optimizes routes and provides time estimates with better data extraction.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.tools.place_tool import PlaceResult, PlaceTool
from src.utils.logger import get_logger


class TimeSlot(BaseModel):
    """Time slot for a plan step."""

    start_time: str = Field(description="Start time in HH:MM format")
    end_time: str = Field(description="End time in HH:MM format")
    duration_minutes: int = Field(description="Duration in minutes")


class PlanStep(BaseModel):
    """Single step in an itinerary."""

    step_number: int = Field(description="Step number in sequence")
    place: PlaceResult = Field(description="Place details")
    time_slot: Optional[TimeSlot] = Field(
        default=None, description="Optional time slot"
    )
    activity: str = Field(description="Suggested activity at this location")
    estimated_duration_minutes: int = Field(
        default=60, description="Estimated time at location"
    )
    travel_time_minutes: Optional[int] = Field(
        default=None, description="Travel time from previous location"
    )
    notes: Optional[str] = Field(default=None, description="Additional notes")
    personalization: Optional[str] = Field(
        default=None, description="Personalized note"
    )
    group_note: Optional[str] = Field(default=None, description="Group-specific note")
    budget_note: Optional[str] = Field(default=None, description="Budget note")


class Itinerary(BaseModel):
    """Complete itinerary plan."""

    title: str = Field(description="Itinerary title")
    description: str = Field(description="Brief description")
    total_duration_minutes: int = Field(description="Total duration")
    total_locations: int = Field(description="Number of locations")
    steps: List[PlanStep] = Field(description="Ordered list of steps")
    start_time: Optional[str] = Field(default=None, description="Suggested start time")
    end_time: Optional[str] = Field(default=None, description="Suggested end time")
    total_distance_km: Optional[float] = Field(
        default=None, description="Total walking distance"
    )
    recommendations: List[str] = Field(
        default_factory=list, description="General recommendations"
    )
    estimated_cost: Optional[str] = Field(
        default=None, description="Estimated cost level"
    )
    metadata: Dict[str, Any] = Field(
        default_factory=dict, description="Additional metadata"
    )


class PlanTool:
    """
    Tool for generating optimized itineraries with multiple locations.
    Integrates with PlaceTool for location search and adds routing logic.
    """

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize plan tool."""
        self.settings = settings or get_settings()
        self.place_tool = PlaceTool(settings)
        self.logger = get_logger("plan_tool")

    async def create_plan(
        self,
        query: str,
        city: str,
        num_locations: int = 3,
        lat: Optional[float] = None,
        lon: Optional[float] = None,
        start_time: Optional[str] = None,
        plan_type: str = "casual",  # casual, quick, full_day
        preferences: Optional[List[str]] = None,
        duration: Optional[str] = None,
        num_people: Optional[int] = None,
        vibe: Optional[str] = None,
        budget: Optional[str] = None,
        transport: Optional[str] = None,
    ) -> Itinerary:
        """
        Create an itinerary plan based on user query.

        Args:
            query: User's plan query (e.g., "bar hopping", "tourist day")
            city: City name
            num_locations: Number of locations to include (2-10)
            lat: Optional starting latitude
            lon: Optional starting longitude
            start_time: Optional start time (HH:MM format)
            plan_type: Type of plan (casual, quick, full_day)
            preferences: Optional list of preferences
            duration: Duration string (e.g., "2 hours", "evening")
            num_people: Number of people in group
            vibe: Desired vibe (e.g., "romantic", "party", "chill")
            budget: Budget level ("low", "medium", "high")
            transport: Transport mode ("walking", "car", "public")

        Returns:
            Complete Itinerary object

        Example:
            >>> plan = await plan_tool.create_plan(
            ...     query="bar hopping",
            ...     city="Zaragoza",
            ...     num_locations=4,
            ...     start_time="20:00",
            ...     plan_type="casual",
            ...     vibe="party"
            ... )
        """
        self.logger.info(
            "creating_plan",
            query=query,
            city=city,
            num_locations=num_locations,
            plan_type=plan_type,
            vibe=vibe,
            duration=duration,
        )

        # Validate inputs
        num_locations = max(2, min(10, num_locations))

        # Parse duration if provided
        duration_minutes = self._parse_duration(duration) if duration else None
        
        # Determine duration per location based on plan type or parsed duration
        if duration_minutes:
            default_duration = duration_minutes // num_locations
        else:
            duration_map = {
                "quick": 30,  # 30 min per location
                "casual": 60,  # 1 hour per location
                "full_day": 90,  # 1.5 hours per location
            }
            default_duration = duration_map.get(plan_type, 60)

        # Search for places
        places = await self.place_tool.search_places(
            query=query,
            city=city,
            lat=lat,
            lon=lon,
            radius_km=10,  # Wider radius for plans
            max_results=num_locations * 2,  # Get more to optimize from
        )

        if not places:
            self.logger.warning("no_places_found", query=query, city=city)
            raise ValueError(f"No places found for '{query}' in {city}")

        # Select best locations (by rating/distance)
        selected_places = self._select_best_places(
            places, num_locations, preferences
        )

        # Optimize route (simple nearest-neighbor for now)
        optimized_route = self._optimize_route(selected_places, lat, lon)

        # Build steps with time slots
        steps = []
        current_time = self._parse_time(start_time) if start_time else None

        for i, place in enumerate(optimized_route):
            # Calculate travel time from previous location
            travel_time = 0
            if i > 0:
                travel_time = self._estimate_travel_time(
                    optimized_route[i - 1], place
                )

            # Create time slot if start_time was provided
            time_slot = None
            if current_time:
                start = current_time
                current_time += timedelta(minutes=travel_time + default_duration)
                time_slot = TimeSlot(
                    start_time=start.strftime("%H:%M"),
                    end_time=current_time.strftime("%H:%M"),
                    duration_minutes=default_duration,
                )

            # Generate activity suggestion
            activity = self._suggest_activity(place, query, plan_type, vibe)

            step = PlanStep(
                step_number=i + 1,
                place=place,
                time_slot=time_slot,
                activity=activity,
                estimated_duration_minutes=default_duration,
                travel_time_minutes=travel_time if i > 0 else None,
            )
            steps.append(step)

        # Calculate totals
        total_duration = sum(s.estimated_duration_minutes for s in steps) + sum(
            s.travel_time_minutes or 0 for s in steps
        )
        total_distance = self._calculate_total_distance(optimized_route)

        # Generate recommendations
        recommendations = self._generate_recommendations(
            optimized_route, plan_type, city, num_people, vibe
        )

        # Personalize itinerary
        personalized_steps = self._personalize_itinerary(
            steps, num_people, vibe, budget
        )

        # Estimate cost
        estimated_cost = self._estimate_cost(personalized_steps, budget)

        # Build itinerary
        itinerary = Itinerary(
            title=self._generate_title(query, city, num_locations),
            description=f"{plan_type.replace('_', ' ').title()} plan with {num_locations} locations in {city}",
            total_duration_minutes=total_duration,
            total_locations=num_locations,
            steps=personalized_steps,
            start_time=steps[0].time_slot.start_time if steps[0].time_slot else None,
            end_time=steps[-1].time_slot.end_time if steps[-1].time_slot else None,
            total_distance_km=round(total_distance, 2) if total_distance else None,
            recommendations=recommendations,
            estimated_cost=estimated_cost,
            metadata={
                "created_at": datetime.now().isoformat(),
                "vibe": vibe or "neutral",
                "group_size": num_people or 1,
                "transport": transport or "walking",
                "budget": budget or "medium",
            },
        )

        self.logger.info(
            "plan_created",
            title=itinerary.title,
            locations=num_locations,
            duration=total_duration,
        )

        return itinerary

    def _parse_duration(self, duration_str: str) -> int:
        """Convert duration string to minutes."""
        duration_lower = duration_str.lower()

        mapping = {
            "quick": 30,
            "rápido": 30,
            "30 min": 30,
            "1 hour": 60,
            "una hora": 60,
            "1h": 60,
            "2 hours": 120,
            "dos horas": 120,
            "2h": 120,
            "afternoon": 180,
            "tarde": 180,
            "evening": 240,
            "noche": 240,
            "full_day": 480,
            "todo el día": 480,
            "full day": 480,
            "un día": 480,
            "un dia": 480,
            "1 día": 480,
            "1 dia": 480,
            "ida y vuelta": 480,
            "day trip": 480,
        }

        for key, minutes in mapping.items():
            if key in duration_lower:
                return minutes

        # Default: 2 hours if can't parse
        return 120

    def _select_best_places(
        self,
        places: List[PlaceResult],
        num_needed: int,
        preferences: Optional[List[str]] = None,
    ) -> List[PlaceResult]:
        """Select best places based on rating and preferences."""
        # Filter by preferences if provided
        if preferences:
            filtered = [
                p
                for p in places
                if any(
                    pref.lower() in (p.type or "").lower()
                    or pref.lower() in (p.name or "").lower()
                    for pref in preferences
                )
            ]
            if filtered:
                places = filtered

        # Sort by rating (descending)
        sorted_places = sorted(
            places, key=lambda p: p.google_rating or 0, reverse=True
        )

        return sorted_places[:num_needed]

    def _optimize_route(
        self,
        places: List[PlaceResult],
        start_lat: Optional[float] = None,
        start_lon: Optional[float] = None,
    ) -> List[PlaceResult]:
        """
        Optimize route using nearest-neighbor algorithm.
        More sophisticated routing could use Google Maps API.
        """
        if not places:
            return []

        if len(places) <= 2:
            return places

        # Simple nearest-neighbor heuristic
        route = []
        remaining = places.copy()

        # Start from user location if provided, otherwise first place
        if start_lat and start_lon:
            current_lat, current_lon = start_lat, start_lon
        else:
            first = remaining.pop(0)
            route.append(first)
            current_lat = first.coordinates.get("lat") if first.coordinates else None
            current_lon = first.coordinates.get("lon") if first.coordinates else None

        # Find nearest neighbor iteratively
        while remaining:
            nearest = min(
                remaining,
                key=lambda p: self._distance(
                    current_lat,
                    current_lon,
                    p.coordinates.get("lat") if p.coordinates else None,
                    p.coordinates.get("lon") if p.coordinates else None,
                ),
            )
            route.append(nearest)
            remaining.remove(nearest)
            current_lat = (
                nearest.coordinates.get("lat") if nearest.coordinates else None
            )
            current_lon = (
                nearest.coordinates.get("lon") if nearest.coordinates else None
            )

        return route

    def _distance(
        self,
        lat1: Optional[float],
        lon1: Optional[float],
        lat2: Optional[float],
        lon2: Optional[float],
    ) -> float:
        """Calculate Haversine distance between two points."""
        if None in [lat1, lon1, lat2, lon2]:
            return float("inf")

        from math import asin, cos, radians, sin, sqrt

        R = 6371  # Earth radius in km

        lat1, lon1, lat2, lon2 = map(radians, [lat1, lon1, lat2, lon2])
        dlat = lat2 - lat1
        dlon = lon2 - lon1

        a = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
        c = 2 * asin(sqrt(a))

        return R * c

    def _estimate_travel_time(
        self, place1: PlaceResult, place2: PlaceResult
    ) -> int:
        """Estimate travel time between two places (walking)."""
        lat1 = place1.coordinates.get("lat") if place1.coordinates else None
        lon1 = place1.coordinates.get("lon") if place1.coordinates else None
        lat2 = place2.coordinates.get("lat") if place2.coordinates else None
        lon2 = place2.coordinates.get("lon") if place2.coordinates else None

        distance_km = self._distance(lat1, lon1, lat2, lon2)

        # Assume walking speed of 5 km/h
        time_minutes = int((distance_km / 5) * 60)

        # Minimum 5 minutes
        return max(5, time_minutes)

    def _calculate_total_distance(self, places: List[PlaceResult]) -> float:
        """Calculate total walking distance for route."""
        total = 0.0
        for i in range(len(places) - 1):
            lat1 = places[i].coordinates.get("lat") if places[i].coordinates else None
            lon1 = places[i].coordinates.get("lon") if places[i].coordinates else None
            lat2 = (
                places[i + 1].coordinates.get("lat")
                if places[i + 1].coordinates
                else None
            )
            lon2 = (
                places[i + 1].coordinates.get("lon")
                if places[i + 1].coordinates
                else None
            )
            total += self._distance(lat1, lon1, lat2, lon2)
        return total

    def _parse_time(self, time_str: str) -> datetime:
        """Parse time string to datetime."""
        try:
            hour, minute = map(int, time_str.split(":"))
            return datetime.now().replace(hour=hour, minute=minute, second=0)
        except Exception:
            return datetime.now()

    def _suggest_activity(
        self,
        place: PlaceResult,
        query: str,
        plan_type: str,
        vibe: Optional[str] = None,
    ) -> str:
        """Generate activity suggestion for a place."""
        place_type = (place.type or "").lower()

        # Vibe-based activities
        if vibe:
            vibe_activities = {
                "romantic": "Enjoy a romantic moment together",
                "party": "Have fun and enjoy the atmosphere",
                "adventure": "Explore and discover something new",
                "chill": "Relax and unwind",
            }
            if vibe in vibe_activities:
                return vibe_activities[vibe]

        # Type-based activities
        if "bar" in place_type or "bar" in query.lower():
            return "Enjoy drinks and ambiance"
        elif "restaurant" in place_type or "restaurant" in query.lower():
            return "Have a meal and relax"
        elif "museum" in place_type:
            return "Explore exhibits"
        elif "park" in place_type:
            return "Take a leisurely walk"
        elif "cafe" in place_type or "coffee" in place_type:
            return "Grab a coffee and snack"
        else:
            return "Spend some time exploring"

    def _generate_title(self, query: str, city: str, num_locations: int) -> str:
        """Generate catchy title for itinerary."""
        return f"{query.title()} in {city} - {num_locations} Locations"

    def _generate_recommendations(
        self,
        places: List[PlaceResult],
        plan_type: str,
        city: str,
        num_people: Optional[int] = None,
        vibe: Optional[str] = None,
    ) -> List[str]:
        """Generate general recommendations for the plan."""
        recommendations = []

        if plan_type == "quick":
            recommendations.append("This is a quick tour - perfect for limited time")
        elif plan_type == "full_day":
            recommendations.append("Pack water and wear comfortable shoes")

        recommendations.append("Check opening hours before visiting")
        recommendations.append("Consider local transportation options")

        avg_rating = sum(p.google_rating or 0 for p in places) / len(places)
        if avg_rating >= 4.5:
            recommendations.append("All locations are highly rated!")

        if num_people and num_people > 4:
            recommendations.append("Consider making reservations for large group")

        if vibe == "romantic":
            recommendations.append("Book in advance for a better experience")
        elif vibe == "party":
            recommendations.append("Check dress codes and peak hours")

        return recommendations

    def _personalize_itinerary(
        self,
        steps: List[PlanStep],
        num_people: Optional[int] = None,
        vibe: Optional[str] = None,
        budget: Optional[str] = None,
    ) -> List[PlanStep]:
        """Add personalization based on group."""
        personalization_notes = {
            "romantic": "👫 Reserva con anticipación, estas son buenas opciones para parejas",
            "party": "🎉 ¡A divertirse! Estos son los mejores lugares para un buen ambiente",
            "adventure": "🚀 Prepárate para explorar lugares únicos y emocionantes",
            "chill": "☕ Perfectos para relajarse y desconectar",
        }

        for step in steps:
            if vibe:
                step.personalization = personalization_notes.get(
                    vibe, "Disfruta este lugar"
                )

            if num_people and num_people > 4:
                step.group_note = "✅ Excelente lugar para grupos grandes"

            if budget == "low":
                step.budget_note = "💰 Opción económica"
            elif budget == "high":
                step.budget_note = "💎 Opción premium"

        return steps

    def _estimate_cost(
        self, steps: List[PlanStep], budget_level: Optional[str] = None
    ) -> str:
        """Estimate total cost."""
        if budget_level == "high":
            return "$$$"
        elif budget_level == "medium":
            return "$$"
        elif budget_level == "low":
            return "$"
        else:
            return "$$"
