"""
Instagram hashtag tool for visual vibes and trends.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.tools import tool

from src.utils.logger import get_logger

logger = get_logger("instagram_tool")


@tool
async def instagram_hashtag_tool(
    place_name: str,
    location: str = "Zaragoza",
    hashtags: Optional[list] = None,
    limit: int = 20,
) -> Dict[str, Any]:
    """
    Get visual vibes and trends from Instagram using hashtags.
    
    Args:
        place_name: Name of the place
        location: Location (default: "Zaragoza")
        hashtags: Optional list of hashtags to search
        limit: Number of posts to analyze (default: 20)
    
    Returns:
        Instagram data with visual vibes and trends
    """
    try:
        logger.info(f"Instagram search: {place_name} in {location}")
        
        return {
            "place_name": place_name,
            "posts": [],
            "vibe_analysis": {},
            "message": "Instagram tool not yet implemented. Will use Instagram API.",
        }
        
    except Exception as e:
        logger.error(f"Error in Instagram search: {str(e)}")
        return {"error": True, "message": f"Could not get Instagram data: {str(e)}"}

