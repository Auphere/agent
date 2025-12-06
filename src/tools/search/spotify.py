"""
Spotify API tool for venue music and vibe matching.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.tools import tool

from src.utils.logger import get_logger

logger = get_logger("spotify_tool")


@tool
async def spotify_api_tool(
    venue_name: str,
    location: str = "Zaragoza",
) -> Dict[str, Any]:
    """
    Get music/playlist information for a venue to match vibes.
    
    Args:
        venue_name: Name of the venue
        location: Location (default: "Zaragoza")
    
    Returns:
        Music data and vibe analysis from Spotify
    """
    try:
        logger.info(f"Spotify search: {venue_name} in {location}")
        
        return {
            "venue_name": venue_name,
            "playlists": [],
            "music_vibe": {},
            "message": "Spotify tool not yet implemented. Will use Spotify API.",
        }
        
    except Exception as e:
        logger.error(f"Error in Spotify search: {str(e)}")
        return {"error": True, "message": f"Could not get Spotify data: {str(e)}"}

