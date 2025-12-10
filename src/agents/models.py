"""Shared Pydantic models for agents."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class PlanningContext(BaseModel):
    """
    Comprehensive planning context that the agent needs to gather 
    before generating a complete plan.
    """
    
    # Core intent
    primary_intent: Optional[str] = Field(None, description="Main intent: romantic_dinner, night_out_friends, weekend_trip, etc.")
    secondary_intent: Optional[str] = Field(None, description="Secondary intent: low_budget, luxury, adventure, etc.")
    
    # Timing
    date: Optional[str] = Field(None, description="ISO date for the plan")
    start_time: Optional[str] = Field(None, description="Start time (e.g., '20:00')")
    duration_hours: Optional[float] = Field(None, description="Expected duration in hours (default 3-4)")
    
    # Location
    city: Optional[str] = Field(None, description="City for the plan")
    zones: Optional[List[str]] = Field(default_factory=list, description="Preferred neighborhoods/zones")
    
    # Group
    group_size: Optional[int] = Field(None, description="Number of people")
    group_composition: Optional[Literal["couple", "friends", "family", "mixed"]] = Field(
        None, 
        description="Type of group"
    )
    
    # Budget
    budget_total: Optional[float] = Field(None, description="Total budget for the plan")
    budget_per_person: Optional[float] = Field(None, description="Budget per person")
    budget_flexible: bool = Field(True, description="Whether budget is flexible")
    
    # Vibes and preferences
    desired_vibes: List[str] = Field(default_factory=list, description="Desired atmospheres/vibes")
    avoid_vibes: List[str] = Field(default_factory=list, description="Vibes to avoid")
    music_preferences: Optional[List[str]] = Field(default_factory=list, description="Music preferences")
    food_preferences: Optional[List[str]] = Field(default_factory=list, description="Food preferences")
    
    # Constraints
    dietary_restrictions: List[str] = Field(default_factory=list, description="Dietary restrictions")
    accessibility_requirements: List[str] = Field(default_factory=list, description="Accessibility needs")
    time_constraints: Optional[List[str]] = Field(default_factory=list, description="Time constraints")
    
    # Energy level
    energy_level: Optional[Literal["low", "medium", "high"]] = Field(None, description="Desired energy level")
    
    def get_missing_critical_fields(self) -> List[str]:
        """
        Returns a list of critical fields that are still missing.
        Critical fields: group_size, desired_vibes, approximate time/duration.
        """
        missing = []
        
        if not self.group_size:
            missing.append("group_size")
        
        if not self.desired_vibes:
            missing.append("desired_vibes")
        
        if not self.start_time and not self.date:
            missing.append("approximate_time")
        
        return missing
    
    def is_ready_for_generation(self) -> bool:
        """Returns True if we have enough information to generate a plan."""
        return len(self.get_missing_critical_fields()) == 0


class PlanLocation(BaseModel):
    """Location information for a plan stop."""
    
    address: str
    zone: Optional[str] = None
    lat: float
    lng: float
    travel_time_from_previous_minutes: Optional[int] = None
    travel_mode: Optional[Literal["walk", "car", "public"]] = None


class PlanTiming(BaseModel):
    """Timing information for a plan stop."""
    
    recommended_start: str = Field(..., description="Recommended start time (e.g., '20:00')")
    suggested_duration_minutes: int
    estimated_end: str
    expected_occupancy: Optional[str] = None
    occupancy_recommendation: Optional[str] = None


class PlanDetails(BaseModel):
    """Details about a plan stop."""
    
    vibes: List[str] = Field(default_factory=list)
    target_audience: Optional[List[str]] = None
    music: Optional[str] = None
    noise_level: Optional[Literal["low", "medium", "high"]] = None
    average_spend_per_person: Optional[float] = None


class PlanActions(BaseModel):
    """Available actions for a plan stop."""
    
    can_reserve: bool = False
    reservation_url: Optional[str] = None
    google_maps_url: Optional[str] = None
    phone: Optional[str] = None


class PlanAlternative(BaseModel):
    """Alternative venue for a stop."""
    
    name: str
    reason_not_selected: str
    link: Optional[str] = None


class PlanStop(BaseModel):
    """Represents a single stop within a plan."""

    stop_number: int
    local_id: str = Field(..., description="Place ID or reference")
    name: str
    category: str = Field(..., description="e.g., 'restaurant', 'bar', 'club'")
    type_label: Optional[str] = Field(None, description="e.g., 'Italian restaurant', 'Jazz bar'")
    timing: PlanTiming
    location: PlanLocation
    details: PlanDetails
    selection_reasons: List[str] = Field(default_factory=list)
    actions: PlanActions = Field(default_factory=PlanActions)
    alternatives: Optional[List[PlanAlternative]] = None
    personal_tips: Optional[List[str]] = None


class BudgetBreakdown(BaseModel):
    """Budget breakdown for a plan."""
    
    total: float
    per_person: float
    within_budget: bool
    breakdown: Optional[Dict[str, float]] = None


class PlanMetrics(BaseModel):
    """Success metrics for a plan."""
    
    vibe_match_percent: Optional[float] = None
    average_venue_rating: Optional[float] = None
    success_probability_label: Optional[str] = None


class PlanSummary(BaseModel):
    """Summary metrics for a plan."""
    
    total_duration: str = Field(..., description="Human-readable duration (e.g., '3h 45m')")
    total_distance_km: Optional[float] = None
    budget: BudgetBreakdown
    metrics: Optional[PlanMetrics] = None


class PlanExecution(BaseModel):
    """Execution details for a plan."""
    
    date: Optional[str] = None
    start_time: Optional[str] = None
    duration_hours: Optional[float] = None
    city: Optional[str] = None
    zones: Optional[List[str]] = None
    group_size: Optional[int] = None
    group_composition: Optional[str] = None


class PlanJson(BaseModel):
    """
    Complete structured plan JSON that the planning agent should produce.
    This is the target output format for plan generation.
    """
    
    plan_id: str
    title: str
    description: str
    category: str
    vibes: List[str]
    tags: List[str]
    execution: PlanExecution
    stops: List[PlanStop]
    summary: PlanSummary
    final_recommendations: Optional[List[str]] = None

