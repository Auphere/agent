"""
Trustpilot API tool for reviews and sentiment analysis.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.tools import tool

from src.utils.logger import get_logger

logger = get_logger("trustpilot_tool")


@tool
async def trustpilot_api_tool(
    place_name: str,
    location: str = "Zaragoza",
    language: str = "es",
) -> Dict[str, Any]:
    """
    Get reviews and sentiment analysis from Trustpilot.
    
    Args:
        place_name: Name of the place/business
        location: Location (default: "Zaragoza")
        language: Language for results ("es" or "en")
    
    Returns:
        Reviews and sentiment analysis data
    """
    try:
        logger.info(f"Trustpilot search: {place_name} in {location}")
        
        return {
            "place_name": place_name,
            "reviews": [],
            "average_rating": None,
            "sentiment": None,
            "message": "Trustpilot tool not yet implemented. Will use Trustpilot API.",
        }
        
    except Exception as e:
        logger.error(f"Error in Trustpilot search: {str(e)}")
        return {"error": True, "message": f"Could not get Trustpilot data: {str(e)}"}

