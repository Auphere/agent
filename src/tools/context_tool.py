"""
Tool for updating plan context memory explicitly.

⚠️ DEPRECATED: This tool used PlanMemoryManager which was in-memory and unreliable.

New approach:
- Plan state is automatically extracted from user queries
- Stored in database (ConversationTurn.extra_metadata)
- No explicit tool needed - agents handle it automatically

This file kept for backward compatibility but should not be used.
"""
from typing import List, Optional

from langchain_core.tools import tool


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
    [DEPRECATED] Save new plan details to memory.
    
    This tool is deprecated and no longer functional.
    Plan state is now automatically managed via ConversationTurn metadata.
    
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
        Deprecation message.
    """
    return (
        "⚠️ This tool is deprecated. Plan context is now automatically "
        "extracted and stored. No manual updates needed."
    )

