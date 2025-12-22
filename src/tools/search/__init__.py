"""
Active search tools for the agent.
These tools actively search external sources for place information.
"""

from .web_search import web_search_tool
from .google_places import google_places_tool  # 🎯 BETA: Direct Google Places API
from .trustpilot import trustpilot_api_tool
from .apify_scraping import apify_web_scraping_tool
from .yelp_fusion import yelp_fusion_tool
from .foursquare import foursquare_places_tool
from .google_maps import google_maps_data_tool
from .instagram import instagram_hashtag_tool
from .spotify import spotify_api_tool
from .weather import weather_api_tool

# NEW: Advanced enrichment tools
from .foursquare_v2 import (
    search_foursquare_places,
    get_foursquare_place_enrichment,
)
from .apify_enrichment import (
    scrape_instagram_place,
    scrape_tiktok_place,
    scrape_tripadvisor_reviews,
    get_social_media_summary,
)
from .geocoding import geocode_city_tool

__all__ = [
    "web_search_tool",
    "google_places_tool",
    "trustpilot_api_tool",
    "apify_web_scraping_tool",
    "yelp_fusion_tool",
    "foursquare_places_tool",
    "google_maps_data_tool",
    "instagram_hashtag_tool",
    "spotify_api_tool",
    "weather_api_tool",
    # NEW
    "search_foursquare_places",
    "get_foursquare_place_enrichment",
    "scrape_instagram_place",
    "scrape_tiktok_place",
    "scrape_tripadvisor_reviews",
    "get_social_media_summary",
    "geocode_city_tool",
]


