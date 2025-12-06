"""
Web search tool using DuckDuckGo (free) or SerpAPI for quick searches.

Use for:
- Recent reviews or news about places
- General information and context
- Events happening in the area
- Supplementary data not in Google Places
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger("web_search_tool")


class WebSearchResult(BaseModel):
    """Result from web search."""
    
    title: str = Field(description="Title of the result")
    url: str = Field(description="URL of the result")
    snippet: str = Field(description="Text snippet from the result")
    source: str = Field(description="Source domain")


async def _search_duckduckgo(
    query: str,
    num_results: int = 5,
    region: str = "es-es",
) -> List[Dict[str, Any]]:
    """
    Search using DuckDuckGo Instant Answer API (free, no API key required).
    
    Note: DuckDuckGo HTML API is unofficial and may be rate-limited.
    For production, consider SerpAPI as alternative.
    """
    base_url = "https://api.duckduckgo.com/"
    
    params = {
        "q": query,
        "format": "json",
        "no_html": 1,
        "skip_disambig": 1,
    }
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(base_url, params=params)
            response.raise_for_status()
            data = response.json()
            
            results = []
            
            # Process RelatedTopics
            for topic in data.get("RelatedTopics", [])[:num_results]:
                if isinstance(topic, dict) and "Text" in topic:
                    results.append({
                        "title": topic.get("Text", "")[:100],
                        "url": topic.get("FirstURL", ""),
                        "snippet": topic.get("Text", ""),
                        "source": "duckduckgo",
                    })
            
            # If no RelatedTopics, use Abstract
            if not results and data.get("Abstract"):
                results.append({
                    "title": data.get("Heading", ""),
                    "url": data.get("AbstractURL", ""),
                    "snippet": data.get("Abstract", ""),
                    "source": "duckduckgo",
                })
            
            return results
            
    except Exception as e:
        logger.error(f"DuckDuckGo search error: {str(e)}")
        return []


async def _search_serpapi(
    api_key: str,
    query: str,
    num_results: int = 5,
    location: str = "Zaragoza, Spain",
) -> List[Dict[str, Any]]:
    """
    Search using SerpAPI (paid service, requires API key).
    More reliable and comprehensive than DuckDuckGo.
    """
    base_url = "https://serpapi.com/search"
    
    params = {
        "q": query,
        "api_key": api_key,
        "engine": "google",
        "location": location,
        "num": num_results,
        "hl": "es",  # Interface language
        "gl": "es",  # Country
    }
    
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.get(base_url, params=params)
        response.raise_for_status()
        data = response.json()
        
        results = []
        for result in data.get("organic_results", [])[:num_results]:
            results.append({
                "title": result.get("title", ""),
                "url": result.get("link", ""),
                "snippet": result.get("snippet", ""),
                "source": result.get("displayed_link", ""),
            })
        
        return results


@tool
async def web_search_tool(
    query: str,
    num_results: int = 5,
    language: str = "es",
    location: str = "Zaragoza, Spain",
) -> Dict[str, Any]:
    """
    Search the web for information using DuckDuckGo (free) or SerpAPI.
    
    Use this tool to find:
    - Recent reviews or news about places
    - General information about locations
    - Events happening in the area
    - Context about neighborhoods or areas
    - Supplementary data not in Google Places
    
    Priority: DuckDuckGo (free) first, falls back to SerpAPI if configured.
    
    Args:
        query: Search query (in Spanish or English)
        num_results: Number of results to return (default: 5, max: 10)
        language: Language for results ("es" or "en")
        location: Location context (default: "Zaragoza, Spain")
    
    Returns:
        Dictionary with search results and metadata
    
    Examples:
        - web_search_tool("restaurante La Toscana Zaragoza opiniones")
        - web_search_tool("eventos Zaragoza este fin de semana")
        - web_search_tool("mejor zona de tapas Zaragoza")
    """
    settings = get_settings()
    
    try:
        logger.info(f"Web search: '{query}' (lang: {language}, location: {location})")
        
        results = []
        search_engine = "none"
        
        # Try SerpAPI first if API key is available (more reliable)
        if settings.serpapi_key:
            try:
                logger.info("Using SerpAPI for web search")
                results = await _search_serpapi(
                    api_key=settings.serpapi_key,
                    query=query,
                    num_results=num_results,
                    location=location,
                )
                search_engine = "serpapi"
            except Exception as e:
                logger.warning(f"SerpAPI failed, falling back to DuckDuckGo: {str(e)}")
        
        # Fallback to DuckDuckGo (free, no API key)
        if not results:
            logger.info("Using DuckDuckGo for web search (free)")
            region = "es-es" if language == "es" else "en-us"
            results = await _search_duckduckgo(
                query=query,
                num_results=num_results,
                region=region,
            )
            search_engine = "duckduckgo"
        
        if not results:
            logger.warning(f"No web search results found for: {query}")
            return {
                "query": query,
                "results": [],
                "total_results": 0,
                "language": language,
                "search_engine": search_engine,
                "message": "No web search results found. Try refining the query or using google_places_tool.",
            }
        
        logger.info(f"Found {len(results)} web search results using {search_engine}")
        
        return {
            "query": query,
            "results": results,
            "total_results": len(results),
            "language": language,
            "location": location,
            "search_engine": search_engine,
            "source": "web_search",
        }
        
    except httpx.HTTPError as e:
        logger.error(f"HTTP error in web search: {str(e)}")
        return {
            "error": True,
            "message": f"HTTP error performing web search: {str(e)}",
        }
    except Exception as e:
        logger.error(f"Error in web search: {str(e)}")
        return {
            "error": True,
            "message": f"Could not perform web search: {str(e)}",
        }

