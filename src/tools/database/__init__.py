"""
Database tools for the agent.
These tools query internal databases and user data.

⚠️ BETA VERSION: These are FALLBACK/ANALYTICS tools.
For place searches, prefer external APIs (google_places_tool, web_search_tool, etc.)
Use database tools for:
- Fallback when APIs fail
- Analytics and metrics
- User preferences
- Cached data
"""

from .local_db import search_local_db_fallback_tool
from .metrics import get_local_metrics_tool
from .preferences import get_user_preferences_tool

__all__ = [
    "search_local_db_fallback_tool",
    "get_local_metrics_tool",
    "get_user_preferences_tool",
]

