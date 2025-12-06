"""
Yelp Fusion API tool for alternative reviews and atmosphere data.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from langchain_core.tools import tool

from src.utils.logger import get_logger

logger = get_logger("yelp_tool")


@tool
async def yelp_fusion_tool(
    query: str,
    location: str = "Zaragoza, Spain",
    categories: Optional[str] = None,
    limit: int = 10,
) -> Dict[str, Any]:
    """
    Search Yelp for alternative reviews and atmosphere information.
    
    Args:
        query: Search query
        location: Location to search (default: "Zaragoza, Spain")
        categories: Yelp categories (e.g., "bars", "restaurants")
        limit: Number of results (default: 10)
    
    Returns:
        Yelp reviews and atmosphere data
    """
    try:
        logger.info(f"Yelp search: {query} in {location}")
        
        return {
            "query": query,
            "results": [],
            "total": 0,
            "message": "Yelp Fusion tool not yet implemented. Will use Yelp Fusion API.",
        }
        
    except Exception as e:
        logger.error(f"Error in Yelp search: {str(e)}")
        return {"error": True, "message": f"Could not search Yelp: {str(e)}"}

