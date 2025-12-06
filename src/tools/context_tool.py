"""
Tool for updating plan context memory explicitly.
"""
from typing import List, Optional

from langchain_core.tools import tool

from src.agents.plan_memory import PlanMemoryManager


@tool
def update_plan_context_tool(
    session_id: str,
    duration: Optional[str] = None,
    num_people: Optional[int] = None,
    cities: Optional[List[str]] = None,
    place_types: Optional[List[str]] = None,
    vibe: Optional[str] = None,
    budget: Optional[str] = None,
    transport: Optional[str] = None,
) -> str:
    """
    Save new plan details to memory. Use this IMMEDIATELY when the user provides new information.
    
    Args:
        session_id: The session ID (provided in context)
        duration: Duration of the trip (e.g., "2 hours", "weekend")
        num_people: Number of people
        cities: List of cities
        place_types: List of place types (e.g., "bars", "museums")
        vibe: Vibe/atmosphere (e.g., "romantic", "party")
        budget: Budget level (low, medium, high)
        transport: Transport mode
        
    Returns:
        Confirmation message.
    """
    try:
        manager = PlanMemoryManager.get_instance(session_id)
        
        updates = {}
        if duration: updates["duration"] = duration
        if num_people: updates["num_people"] = num_people
        if cities: updates["cities"] = cities
        if place_types: updates["place_types"] = place_types
        if vibe: updates["vibe"] = vibe
        if budget: updates["budget"] = budget
        if transport: updates["transport"] = transport
        
        if not updates:
            return "No updates provided."
            
        manager.update_plan_context(**updates)
        
        # Get missing fields to guide the agent
        missing = manager.get_missing_for_plan()
        
        return f"Plan context updated. Captured: {', '.join(updates.keys())}. Still missing: {', '.join(missing) if missing else 'None - Plan Ready!'}"
        
    except Exception as e:
        return f"Error updating context: {str(e)}"

