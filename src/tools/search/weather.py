"""
Weather API tool using OpenWeather API for context about indoor/outdoor recommendations.

Use for:
- Deciding between indoor/outdoor venues
- Providing context for recommendations
- Timing suggestions based on weather
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger
from src.utils.cache_manager import get_cache_manager

logger = get_logger("weather_tool")


class WeatherData(BaseModel):
    """Weather data structure."""
    
    temperature: float
    feels_like: float
    humidity: int
    description: str
    icon: str
    wind_speed: float
    rain_probability: Optional[float] = None


async def _get_coordinates(city: str) -> Optional[Dict[str, float]]:
    """Get coordinates for a city using OpenWeather Geocoding API."""
    # Zaragoza coordinates (hardcoded for beta)
    city_coords = {
        "zaragoza": {"lat": 41.6488, "lon": -0.8891},
        "madrid": {"lat": 40.4168, "lon": -3.7038},
        "barcelona": {"lat": 41.3851, "lon": 2.1734},
    }
    
    return city_coords.get(city.lower())


async def _fetch_weather_data(
    api_key: str,
    lat: float,
    lon: float,
    language: str = "es",
) -> Dict[str, Any]:
    """
    Fetch weather data from OpenWeather API.
    
    API Docs: https://openweathermap.org/current
    """
    base_url = "https://api.openweathermap.org/data/2.5/weather"
    
    params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": "metric",  # Celsius
        "lang": language,
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(base_url, params=params)
        response.raise_for_status()
        return response.json()


async def _fetch_forecast_data(
    api_key: str,
    lat: float,
    lon: float,
    language: str = "es",
) -> Dict[str, Any]:
    """
    Fetch forecast data from OpenWeather API.
    
    API Docs: https://openweathermap.org/forecast5
    """
    base_url = "https://api.openweathermap.org/data/2.5/forecast"
    
    params = {
        "lat": lat,
        "lon": lon,
        "appid": api_key,
        "units": "metric",
        "lang": language,
    }
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(base_url, params=params)
        response.raise_for_status()
        return response.json()


def _generate_recommendation(weather_data: Dict[str, Any], language: str = "es") -> str:
    """Generate venue recommendation based on weather."""
    temp = weather_data["main"]["temp"]
    description = weather_data["weather"][0]["description"]
    rain = weather_data.get("rain", {}).get("1h", 0) > 0
    
    if language == "es":
        if rain or temp < 10:
            return f"Tiempo: {description} ({temp}°C). Recomiendo lugares interiores, cerrados y acogedores."
        elif temp > 25:
            return f"Tiempo: {description} ({temp}°C). Perfecto para terrazas, lugares al aire libre o con aire acondicionado."
        else:
            return f"Tiempo: {description} ({temp}°C). Buen clima para cualquier tipo de lugar, terrazas o interiores."
    else:
        if rain or temp < 10:
            return f"Weather: {description} ({temp}°C). I recommend indoor, cozy places."
        elif temp > 25:
            return f"Weather: {description} ({temp}°C). Perfect for terraces, outdoor places, or air-conditioned venues."
        else:
            return f"Weather: {description} ({temp}°C). Good weather for any type of place, terraces or indoors."


@tool
async def weather_api_tool(
    location: str = "Zaragoza",
    forecast_days: int = 1,
    language: str = "es",
) -> Dict[str, Any]:
    """
    Get weather information to provide context for indoor/outdoor venue recommendations.
    
    Use this tool to:
    - Decide between indoor vs outdoor venues
    - Provide weather-appropriate suggestions
    - Time recommendations based on forecast
    - Add context to plans (umbrella needed, dress code, etc.)
    
    Args:
        location: City name (default: "Zaragoza")
        forecast_days: Number of days to forecast (1-5, default: 1)
        language: Language for descriptions ("es" or "en")
    
    Returns:
        Current weather, forecast, and venue recommendations
    
    Examples:
        - weather_api_tool("Zaragoza")
        - weather_api_tool("Zaragoza", forecast_days=3, language="en")
    """
    settings = get_settings()
    
    # Check if API key is configured
    if not settings.openweather_api_key:
        logger.warning("OPENWEATHER_API_KEY not configured")
        return {
            "error": True,
            "message": "OpenWeather API key not configured. Please set OPENWEATHER_API_KEY in environment variables.",
        }
    
    try:
        logger.info(f"Fetching weather for {location}")
        
        # Try to get from cache first (TTL: 30 minutes for weather)
        cache = await get_cache_manager()
        cache_key = cache._generate_key(
            "weather",
            location=location,
            forecast_days=forecast_days,
            language=language,
        )
        
        cached_result = await cache.get(cache_key)
        if cached_result:
            logger.info(f"[CACHE HIT] Weather: {location}")
            return cached_result
        
        # Get coordinates
        coords = await _get_coordinates(location)
        if not coords:
            logger.error(f"Unknown location: {location}")
            return {
                "error": True,
                "message": f"Unknown location: {location}. Currently supported: Zaragoza, Madrid, Barcelona.",
            }
        
        # Fetch current weather
        current_data = await _fetch_weather_data(
            api_key=settings.openweather_api_key,
            lat=coords["lat"],
            lon=coords["lon"],
            language=language,
        )
        
        # Process current weather
        current_weather = {
            "temperature": current_data["main"]["temp"],
            "feels_like": current_data["main"]["feels_like"],
            "humidity": current_data["main"]["humidity"],
            "description": current_data["weather"][0]["description"],
            "icon": current_data["weather"][0]["icon"],
            "wind_speed": current_data["wind"]["speed"],
            "clouds": current_data["clouds"]["all"],
        }
        
        # Add rain data if available
        if "rain" in current_data:
            current_weather["rain_1h"] = current_data["rain"].get("1h", 0)
        
        # Generate recommendation
        recommendation = _generate_recommendation(current_data, language)
        
        # Fetch forecast if requested
        forecast_list = []
        if forecast_days > 0:
            try:
                forecast_data = await _fetch_forecast_data(
                    api_key=settings.openweather_api_key,
                    lat=coords["lat"],
                    lon=coords["lon"],
                    language=language,
                )
                
                # Process forecast (take next N days, one per day at noon)
                for i in range(min(forecast_days, 5)):
                    # OpenWeather provides 3-hour intervals, get noon forecast
                    idx = i * 8 + 4  # Approximately noon
                    if idx < len(forecast_data["list"]):
                        forecast_item = forecast_data["list"][idx]
                        forecast_list.append({
                            "date": forecast_item["dt_txt"],
                            "temperature": forecast_item["main"]["temp"],
                            "description": forecast_item["weather"][0]["description"],
                            "rain_probability": forecast_item.get("pop", 0) * 100,  # Probability of precipitation
                        })
            except Exception as e:
                logger.warning(f"Could not fetch forecast: {str(e)}")
        
        logger.info(f"Weather fetched successfully for {location}: {current_weather['temperature']}°C, {current_weather['description']}")
        
        result = {
            "location": location,
            "coordinates": coords,
            "current": current_weather,
            "forecast": forecast_list,
            "recommendation": recommendation,
            "language": language,
            "source": "openweather",
        }
        
        # Cache the result for 30 minutes (1800 seconds)
        await cache.set(cache_key, result, ttl=1800)
        
        return result
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP error fetching weather: {str(e)}")
        return {
            "error": True,
            "message": f"HTTP error fetching weather data: {str(e)}",
        }
    except Exception as e:
        logger.error(f"Error getting weather: {str(e)}")
        return {
            "error": True,
            "message": f"Could not get weather data: {str(e)}",
        }

