"""
Apify integration for web scraping social media and review platforms.

Supports:
- Instagram: place posts, hashtags, location data
- TikTok: place videos, hashtags, trending content
- TripAdvisor: reviews, ratings, detailed place information
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from datetime import datetime

import httpx
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger

logger = get_logger("apify_enrichment")


class ApifyClient:
    """Client for Apify API."""
    
    BASE_URL = "https://api.apify.com/v2"
    
    # Known actor IDs (these are examples, replace with actual actor IDs)
    ACTORS = {
        "instagram_scraper": "apify/instagram-scraper",
        "tiktok_scraper": "clockworks/tiktok-scraper",
        "tripadvisor_scraper": "maxcopell/tripadvisor",
    }
    
    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.logger = get_logger("apify_client")
    
    async def run_actor(
        self,
        actor_id: str,
        input_data: Dict[str, Any],
        timeout: int = 60,
    ) -> Optional[List[Dict[str, Any]]]:
        """
        Run an Apify actor and wait for results.
        
        Args:
            actor_id: Actor identifier (e.g., "apify/instagram-scraper")
            input_data: Actor input parameters
            timeout: Maximum wait time in seconds
            
        Returns:
            List of result items or None on error
        """
        try:
            # Start actor run
            async with httpx.AsyncClient(timeout=120.0) as client:
                response = await client.post(
                    f"{self.BASE_URL}/acts/{actor_id}/runs",
                    params={"token": self.api_key},
                    json=input_data,
                )
                response.raise_for_status()
                run_data = response.json()
                
                run_id = run_data["data"]["id"]
                self.logger.info("apify-actor-started", actor_id=actor_id, run_id=run_id)
                
                # Poll for completion
                start_time = asyncio.get_event_loop().time()
                while True:
                    if (asyncio.get_event_loop().time() - start_time) > timeout:
                        self.logger.warning("apify-actor-timeout", run_id=run_id)
                        return None
                    
                    # Check run status
                    status_response = await client.get(
                        f"{self.BASE_URL}/actor-runs/{run_id}",
                        params={"token": self.api_key},
                    )
                    status_response.raise_for_status()
                    status_data = status_response.json()
                    
                    status = status_data["data"]["status"]
                    
                    if status == "SUCCEEDED":
                        # Get dataset items
                        default_dataset_id = status_data["data"]["defaultDatasetId"]
                        
                        items_response = await client.get(
                            f"{self.BASE_URL}/datasets/{default_dataset_id}/items",
                            params={"token": self.api_key},
                        )
                        items_response.raise_for_status()
                        items = items_response.json()
                        
                        self.logger.info(
                            "apify-actor-success",
                            run_id=run_id,
                            items_count=len(items),
                        )
                        return items
                    
                    elif status in ["FAILED", "ABORTED", "TIMED-OUT"]:
                        self.logger.error("apify-actor-failed", run_id=run_id, status=status)
                        return None
                    
                    # Still running, wait a bit
                    await asyncio.sleep(2)
                    
        except httpx.HTTPStatusError as exc:
            self.logger.error(
                "apify-api-error",
                status_code=exc.response.status_code,
                error=str(exc),
            )
            return None
        except Exception as exc:
            self.logger.error("apify-run-failed", actor_id=actor_id, error=str(exc))
            return None


# LangChain tool wrappers
@tool
async def scrape_instagram_place(
    place_name: str,
    location: str,
    max_posts: int = 20,
) -> str:
    """
    Scrape Instagram posts for a specific place or location.
    
    This tool searches Instagram for posts tagged with a specific place name or location,
    providing recent visual content, user sentiments, and trending insights.
    
    Useful for:
    - Getting real-time visual content of a place
    - Understanding current vibes and popularity
    - Finding what people are posting about recently
    - Discovering hidden gems and popular spots
    
    Args:
        place_name: Name of the place (e.g., "Cafe Central Zaragoza")
        location: City or area (e.g., "Zaragoza, Spain")
        max_posts: Maximum number of posts to scrape (default: 20, max: 50)
        
    Returns:
        Formatted string with Instagram post data including captions, likes, and trends
        
    Example:
        scrape_instagram_place("Cafe Central", "Zaragoza", 10)
    """
    settings = get_settings()
    
    if not settings.apify_api_key:
        return "❌ Apify API key not configured. Please set APIFY_API_KEY."
    
    client = ApifyClient(settings.apify_api_key)
    
    # Prepare search query
    search_query = f"{place_name} {location}"
    hashtag = place_name.replace(" ", "").lower()
    
    input_data = {
        "searchQueries": [search_query],
        "hashtags": [hashtag],
        "resultsLimit": min(max_posts, 50),
        "searchType": "hashtag",
    }
    
    try:
        results = await client.run_actor(
            client.ACTORS["instagram_scraper"],
            input_data,
            timeout=90,
        )
        
        if not results:
            return f"No se encontraron posts de Instagram para '{place_name}'."
        
        # Format results
        output_lines = [f"📸 Instagram: {len(results)} posts recientes para '{place_name}':"]
        
        total_likes = 0
        total_comments = 0
        captions = []
        
        for idx, post in enumerate(results[:10], 1):  # Show first 10
            caption = post.get("caption", "")[:100]  # First 100 chars
            likes = post.get("likesCount", 0)
            comments = post.get("commentsCount", 0)
            timestamp = post.get("timestamp", "")
            
            total_likes += likes
            total_comments += comments
            
            if caption:
                captions.append(caption)
            
            output_lines.append(
                f"{idx}. ❤️ {likes} likes, 💬 {comments} comentarios"
            )
            if caption:
                output_lines.append(f"   \"{caption}...\"")
        
        # Summary
        output_lines.append("")
        output_lines.append(f"📊 Resumen:")
        output_lines.append(f"   Total likes: {total_likes}")
        output_lines.append(f"   Total comentarios: {total_comments}")
        output_lines.append(f"   Engagement promedio: {(total_likes + total_comments) / len(results):.1f}")
        
        return "\n".join(output_lines)
        
    except Exception as exc:
        logger.error("instagram-scrape-failed", place_name=place_name, error=str(exc))
        return f"❌ Error al buscar en Instagram: {str(exc)}"


@tool
async def scrape_tiktok_place(
    place_name: str,
    location: str,
    max_videos: int = 20,
) -> str:
    """
    Scrape TikTok videos for a specific place or location.
    
    This tool searches TikTok for videos tagged with a specific place name or location,
    providing trending content, user experiences, and viral insights.
    
    Useful for:
    - Discovering trending content about a place
    - Understanding what's currently popular
    - Finding authentic user experiences
    - Identifying viral moments and trends
    
    Args:
        place_name: Name of the place (e.g., "Cafe Central Zaragoza")
        location: City or area (e.g., "Zaragoza, Spain")
        max_videos: Maximum number of videos to scrape (default: 20, max: 50)
        
    Returns:
        Formatted string with TikTok video data including views, likes, and trends
        
    Example:
        scrape_tiktok_place("Cafe Central", "Zaragoza", 10)
    """
    settings = get_settings()
    
    if not settings.apify_api_key:
        return "❌ Apify API key not configured. Please set APIFY_API_KEY."
    
    client = ApifyClient(settings.apify_api_key)
    
    # Prepare search query
    search_query = f"{place_name} {location}"
    hashtag = place_name.replace(" ", "").lower()
    
    input_data = {
        "searchQueries": [search_query],
        "hashtags": [hashtag],
        "resultsLimit": min(max_videos, 50),
    }
    
    try:
        results = await client.run_actor(
            client.ACTORS["tiktok_scraper"],
            input_data,
            timeout=90,
        )
        
        if not results:
            return f"No se encontraron videos de TikTok para '{place_name}'."
        
        # Format results
        output_lines = [f"🎵 TikTok: {len(results)} videos recientes para '{place_name}':"]
        
        total_views = 0
        total_likes = 0
        total_shares = 0
        descriptions = []
        
        for idx, video in enumerate(results[:10], 1):  # Show first 10
            description = video.get("text", "")[:100]  # First 100 chars
            views = video.get("playCount", 0)
            likes = video.get("diggCount", 0)
            shares = video.get("shareCount", 0)
            
            total_views += views
            total_likes += likes
            total_shares += shares
            
            if description:
                descriptions.append(description)
            
            output_lines.append(
                f"{idx}. 👁️ {views:,} views, ❤️ {likes:,} likes, 🔄 {shares} shares"
            )
            if description:
                output_lines.append(f"   \"{description}...\"")
        
        # Summary
        output_lines.append("")
        output_lines.append(f"📊 Resumen:")
        output_lines.append(f"   Total vistas: {total_views:,}")
        output_lines.append(f"   Total likes: {total_likes:,}")
        output_lines.append(f"   Total shares: {total_shares}")
        output_lines.append(f"   Engagement promedio: {(total_likes + total_shares) / len(results):.1f}")
        
        return "\n".join(output_lines)
        
    except Exception as exc:
        logger.error("tiktok-scrape-failed", place_name=place_name, error=str(exc))
        return f"❌ Error al buscar en TikTok: {str(exc)}"


@tool
async def scrape_tripadvisor_reviews(
    place_name: str,
    location: str,
    max_reviews: int = 20,
) -> str:
    """
    Scrape TripAdvisor reviews for a specific place.
    
    This tool searches TripAdvisor for reviews and ratings of a specific place,
    providing detailed user feedback, ratings, and recommendations.
    
    Useful for:
    - Getting detailed user reviews and ratings
    - Understanding strengths and weaknesses
    - Finding specific feedback on food, service, ambiance
    - Identifying common themes in reviews
    
    Args:
        place_name: Name of the place (e.g., "Cafe Central")
        location: City or area (e.g., "Zaragoza, Spain")
        max_reviews: Maximum number of reviews to scrape (default: 20, max: 100)
        
    Returns:
        Formatted string with TripAdvisor review data including ratings and summaries
        
    Example:
        scrape_tripadvisor_reviews("Cafe Central", "Zaragoza", 10)
    """
    settings = get_settings()
    
    if not settings.apify_api_key:
        return "❌ Apify API key not configured. Please set APIFY_API_KEY."
    
    client = ApifyClient(settings.apify_api_key)
    
    # Prepare search query
    search_query = f"{place_name}, {location}"
    
    input_data = {
        "searchQuery": search_query,
        "maxReviews": min(max_reviews, 100),
        "includeReviews": True,
        "language": "es",
    }
    
    try:
        results = await client.run_actor(
            client.ACTORS["tripadvisor_scraper"],
            input_data,
            timeout=120,
        )
        
        if not results or len(results) == 0:
            return f"No se encontraron reseñas de TripAdvisor para '{place_name}'."
        
        # TripAdvisor results typically have a single place with reviews
        place_data = results[0] if isinstance(results, list) else results
        
        # Format results
        output_lines = [f"⭐ TripAdvisor: {place_name}"]
        
        # Overall rating
        rating = place_data.get("rating")
        num_reviews = place_data.get("numberOfReviews", 0)
        if rating:
            output_lines.append(f"Rating: {'⭐' * int(rating)} ({rating}/5) - {num_reviews} reseñas")
        
        output_lines.append("")
        
        # Reviews
        reviews = place_data.get("reviews", [])
        if reviews:
            output_lines.append(f"📝 Reseñas recientes ({len(reviews[:10])} de {len(reviews)}):")
            output_lines.append("")
            
            rating_counts = {5: 0, 4: 0, 3: 0, 2: 0, 1: 0}
            
            for idx, review in enumerate(reviews[:10], 1):
                title = review.get("title", "")
                text = review.get("text", "")[:150]  # First 150 chars
                review_rating = review.get("rating", 0)
                date = review.get("publishedDate", "")
                
                if review_rating in rating_counts:
                    rating_counts[review_rating] += 1
                
                stars = "⭐" * review_rating
                output_lines.append(f"{idx}. {stars} - {title}")
                if text:
                    output_lines.append(f"   \"{text}...\"")
                if date:
                    output_lines.append(f"   📅 {date}")
                output_lines.append("")
            
            # Rating distribution
            output_lines.append("📊 Distribución de ratings:")
            for rating_val in sorted(rating_counts.keys(), reverse=True):
                count = rating_counts[rating_val]
                bar = "█" * (count // 2) if count > 0 else ""
                output_lines.append(f"   {'⭐' * rating_val}: {count} {bar}")
        
        return "\n".join(output_lines)
        
    except Exception as exc:
        logger.error("tripadvisor-scrape-failed", place_name=place_name, error=str(exc))
        return f"❌ Error al buscar en TripAdvisor: {str(exc)}"


@tool
async def get_social_media_summary(
    place_name: str,
    location: str,
) -> str:
    """
    Get a comprehensive social media summary for a place across multiple platforms.
    
    This tool combines data from Instagram, TikTok, and TripAdvisor to provide
    a holistic view of a place's online presence and user sentiment.
    
    Use this when you need to:
    - Get overall social media presence and popularity
    - Understand user sentiment across platforms
    - Find trending content and viral moments
    - Make recommendations based on current buzz
    
    Args:
        place_name: Name of the place (e.g., "Cafe Central")
        location: City or area (e.g., "Zaragoza, Spain")
        
    Returns:
        Comprehensive summary combining all social media insights
        
    Example:
        get_social_media_summary("Cafe Central", "Zaragoza")
    """
    settings = get_settings()
    
    if not settings.apify_api_key:
        return "❌ Apify API key not configured. Please set APIFY_API_KEY."
    
    # Run all scrapers in parallel for speed
    instagram_task = scrape_instagram_place.ainvoke({
        "place_name": place_name,
        "location": location,
        "max_posts": 10,
    })
    
    tiktok_task = scrape_tiktok_place.ainvoke({
        "place_name": place_name,
        "location": location,
        "max_videos": 10,
    })
    
    tripadvisor_task = scrape_tripadvisor_reviews.ainvoke({
        "place_name": place_name,
        "location": location,
        "max_reviews": 10,
    })
    
    try:
        instagram_result, tiktok_result, tripadvisor_result = await asyncio.gather(
            instagram_task,
            tiktok_task,
            tripadvisor_task,
            return_exceptions=True,
        )
        
        output_lines = [f"🌐 Resumen de Redes Sociales: {place_name}"]
        output_lines.append("=" * 60)
        output_lines.append("")
        
        # Instagram
        if not isinstance(instagram_result, Exception):
            output_lines.append(instagram_result)
            output_lines.append("")
        
        # TikTok
        if not isinstance(tiktok_result, Exception):
            output_lines.append(tiktok_result)
            output_lines.append("")
        
        # TripAdvisor
        if not isinstance(tripadvisor_result, Exception):
            output_lines.append(tripadvisor_result)
        
        return "\n".join(output_lines)
        
    except Exception as exc:
        logger.error("social-media-summary-failed", place_name=place_name, error=str(exc))
        return f"❌ Error al obtener resumen de redes sociales: {str(exc)}"

