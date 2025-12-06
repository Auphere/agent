# Agent Tools Architecture

This directory contains all tools available to the Auphere agent, organized by category.

## Tool Categories

### 1. Search Tools (`search/`)
Active search tools that query external sources for place information.

| Tool | File | Purpose | API Required |
|------|------|---------|--------------|
| `web_search_tool` | `web_search.py` | DuckDuckGo/SerpAPI for quick searches | SerpAPI (optional) |
| `google_places_tool` | `google_places.py` | Official Google Places data | Google Places API |
| `trustpilot_api_tool` | `trustpilot.py` | Reviews + sentiment analysis | Trustpilot API |
| `apify_web_scraping_tool` | `apify_scraping.py` | Web scraping for occupancy, events | Apify API |
| `yelp_fusion_tool` | `yelp_fusion.py` | Alternative reviews + atmosphere | Yelp Fusion API |
| `foursquare_places_tool` | `foursquare.py` | Real-time popularity data | Foursquare API |
| `google_maps_data_tool` | `google_maps.py` | Hours, photos, occupancy | Google Maps API |
| `instagram_hashtag_tool` | `instagram.py` | Visual vibes, trends | Instagram API |
| `spotify_api_tool` | `spotify.py` | Venue music for vibe matching | Spotify API |
| `weather_api_tool` | `weather.py` | Weather context (indoor/outdoor) | OpenWeather API |

### 2. Database Tools (`database/`)
Tools that query internal databases and user data.

| Tool | File | Purpose | Data Source |
|------|------|---------|-------------|
| `search_your_db_tool` | `local_db.py` | Query Rust Places microservice | auphere-places |
| `get_local_metrics_tool` | `metrics.py` | B2B metrics (occupancy, trends) | PostgreSQL |
| `get_user_preferences_tool` | `preferences.py` | User saved preferences | PostgreSQL |

### 3. Processing Tools (`processing/`)
Tools that process and calculate data for plans and recommendations.

| Tool | File | Purpose | Dependencies |
|------|------|---------|--------------|
| `validate_availability_tool` | `availability.py` | Check real-time availability | search tools |
| `calculate_route_tool` | `routing.py` | Distance, time, transport | Google Maps API |
| `generate_itinerary_tool` | `itinerary.py` | Create plan with timings | routing, local_db |
| `rank_by_score_tool` | `scoring.py` | Custom scoring by requirements | all search tools |

## Implementation Status

### ✅ Existing Tools (Legacy)
- `place_tool.py` - Place search (will be enhanced/replaced by search_your_db_tool)
- `plan_tool.py` - Plan generation (will be enhanced by generate_itinerary_tool)
- `context_tool.py` - Plan context memory (keeping as is)

### 🚧 To Implement (STAGE 2)
All 17 tools listed above need to be fully implemented.

## Tool Development Guidelines

### 1. Tool Signature
Every tool should:
- Use `@tool` decorator from LangChain
- Have clear docstring with examples
- Accept language parameter ("es" or "en") when applicable
- Return structured dict with error handling

### 2. Error Handling
```python
try:
    # Tool logic
    return {
        "success": True,
        "data": results,
    }
except Exception as e:
    logger.error(f"Error in tool: {str(e)}")
    return {
        "error": True,
        "message": f"Could not complete action: {str(e)}",
    }
```

### 3. Bilingual Support
Tools should support Spanish and English:
```python
@tool
async def example_tool(
    query: str,
    language: str = "es",  # or "en"
) -> Dict[str, Any]:
    """
    Tool description in English.
    Descripción de la herramienta en español.
    """
    # Implementation
```

### 4. API Key Management
All API keys should be:
- Defined in `src/config/settings.py`
- Loaded from environment variables
- Never hardcoded in tool files

Example:
```python
settings = get_settings()
api_key = settings.google_places_api_key
```

## Tool Registry

All tools are registered in `tool_registry.py`:

```python
def get_available_tools() -> List[BaseTool]:
    """Return all available tools for the agent."""
    return [
        # Search tools
        web_search_tool,
        google_places_tool,
        # ... etc
        
        # Database tools
        search_your_db_tool,
        # ... etc
        
        # Processing tools
        generate_itinerary_tool,
        # ... etc
    ]
```

## Next Steps (STAGE 2)

1. Implement each tool following the template
2. Add API keys to `settings.py`
3. Write unit tests for each tool
4. Update tool registry
5. Document API requirements and costs
6. Add rate limiting where needed

## Testing

Each tool should have tests in `tests/tools/`:
- Unit tests for logic
- Integration tests with mock APIs
- Error handling tests

## Cost Monitoring

Tools that use paid APIs should log usage for cost tracking:
```python
logger.info(f"API call: {api_name}, cost_estimate: ${cost}")
```

