"""
User preferences tool for retrieving saved user preferences.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.tools import tool

from src.utils.logger import get_logger

logger = get_logger("preferences_tool")


@tool
async def get_user_preferences_tool(
    user_id: str,
    preference_type: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Get saved user preferences (favorite types, budget, vibe preferences, etc.).
    
    Args:
        user_id: User ID
        preference_type: Specific preference type to retrieve (optional)
    
    Returns:
        User preferences data
    """
    try:
        logger.info(f"Getting preferences for user {user_id}")
        
        return {
            "user_id": user_id,
            "preferences": {},
            "message": "User preferences tool not yet implemented. Will query PostgreSQL.",
        }
        
    except Exception as e:
        logger.error(f"Error getting preferences: {str(e)}")
        return {"error": True, "message": f"Could not get preferences: {str(e)}"}

