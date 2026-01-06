"""
Rate Limiting for External API Calls.

Implements a sliding window rate limiter using Redis for:
- Google Places API
- OpenAI API
- Foursquare API
- Weather API
- Other external services

Benefits:
- Prevents API quota exhaustion
- Protects against accidental abuse
- Graceful degradation when limits hit
- Distributed (works across multiple workers)
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum

from src.utils.logger import get_logger
from src.utils.cache_manager import get_cache_manager

logger = get_logger("rate_limiter")


class RateLimitExceeded(Exception):
    """Raised when rate limit is exceeded."""
    
    def __init__(self, api_name: str, retry_after: int):
        self.api_name = api_name
        self.retry_after = retry_after
        super().__init__(f"Rate limit exceeded for {api_name}. Retry after {retry_after}s")


@dataclass
class RateLimitConfig:
    """Configuration for a rate limit."""
    requests_per_minute: int
    requests_per_hour: int
    requests_per_day: int
    burst_limit: int  # Max requests in a short burst


class APIName(str, Enum):
    """Known API names for rate limiting."""
    GOOGLE_PLACES = "google_places"
    OPENAI = "openai"
    FOURSQUARE = "foursquare"
    WEATHER = "weather"
    APIFY = "apify"


# Default rate limits per API
DEFAULT_LIMITS: Dict[str, RateLimitConfig] = {
    APIName.GOOGLE_PLACES: RateLimitConfig(
        requests_per_minute=60,
        requests_per_hour=1000,
        requests_per_day=10000,
        burst_limit=10,
    ),
    APIName.OPENAI: RateLimitConfig(
        requests_per_minute=500,  # Higher for OpenAI
        requests_per_hour=5000,
        requests_per_day=50000,
        burst_limit=50,
    ),
    APIName.FOURSQUARE: RateLimitConfig(
        requests_per_minute=30,
        requests_per_hour=500,
        requests_per_day=5000,
        burst_limit=5,
    ),
    APIName.WEATHER: RateLimitConfig(
        requests_per_minute=60,
        requests_per_hour=1000,
        requests_per_day=10000,
        burst_limit=10,
    ),
    APIName.APIFY: RateLimitConfig(
        requests_per_minute=10,  # Conservative for scraping
        requests_per_hour=100,
        requests_per_day=1000,
        burst_limit=3,
    ),
}


class RateLimiter:
    """
    Distributed rate limiter using Redis sliding window.
    
    Usage:
        limiter = RateLimiter()
        
        # Check if request is allowed
        if await limiter.is_allowed("google_places"):
            # Make API call
            pass
        else:
            # Handle rate limit
            pass
        
        # Or use context manager
        async with limiter.acquire("google_places"):
            # Make API call
            pass
    """
    
    def __init__(self, custom_limits: Optional[Dict[str, RateLimitConfig]] = None):
        """
        Initialize rate limiter.
        
        Args:
            custom_limits: Override default limits for specific APIs
        """
        self.limits = {**DEFAULT_LIMITS}
        if custom_limits:
            self.limits.update(custom_limits)
        
        logger.info("rate-limiter-initialized", apis=list(self.limits.keys()))
    
    async def _get_cache(self):
        """Get cache manager."""
        return await get_cache_manager()
    
    def _get_keys(self, api_name: str) -> Dict[str, str]:
        """Get Redis keys for the API."""
        return {
            "minute": f"ratelimit:{api_name}:minute",
            "hour": f"ratelimit:{api_name}:hour",
            "day": f"ratelimit:{api_name}:day",
        }
    
    async def is_allowed(self, api_name: str) -> bool:
        """
        Check if a request to the API is allowed.
        
        Args:
            api_name: Name of the API
            
        Returns:
            True if allowed, False if rate limited
        """
        config = self.limits.get(api_name)
        if not config:
            # Unknown API - allow by default
            return True
        
        cache = await self._get_cache()
        if not cache._enabled or not cache._redis:
            # Cache disabled - allow all (fallback to no limiting)
            return True
        
        keys = self._get_keys(api_name)
        current_time = int(time.time())
        
        try:
            # Check minute limit
            minute_key = keys["minute"]
            minute_count = await cache._redis.get(minute_key)
            minute_count = int(minute_count) if minute_count else 0
            
            if minute_count >= config.requests_per_minute:
                logger.warning(
                    "rate-limit-minute-exceeded",
                    api=api_name,
                    count=minute_count,
                    limit=config.requests_per_minute,
                )
                return False
            
            # Check hour limit
            hour_key = keys["hour"]
            hour_count = await cache._redis.get(hour_key)
            hour_count = int(hour_count) if hour_count else 0
            
            if hour_count >= config.requests_per_hour:
                logger.warning(
                    "rate-limit-hour-exceeded",
                    api=api_name,
                    count=hour_count,
                    limit=config.requests_per_hour,
                )
                return False
            
            # Check day limit
            day_key = keys["day"]
            day_count = await cache._redis.get(day_key)
            day_count = int(day_count) if day_count else 0
            
            if day_count >= config.requests_per_day:
                logger.warning(
                    "rate-limit-day-exceeded",
                    api=api_name,
                    count=day_count,
                    limit=config.requests_per_day,
                )
                return False
            
            return True
            
        except Exception as e:
            logger.error("rate-limit-check-failed", api=api_name, error=str(e))
            # On error, allow the request (fail open)
            return True
    
    async def record_request(self, api_name: str) -> None:
        """
        Record a request to the API.
        
        Call this after making a successful API call.
        
        Args:
            api_name: Name of the API
        """
        cache = await self._get_cache()
        if not cache._enabled or not cache._redis:
            return
        
        keys = self._get_keys(api_name)
        
        try:
            pipe = cache._redis.pipeline()
            
            # Increment minute counter (expires in 60s)
            pipe.incr(keys["minute"])
            pipe.expire(keys["minute"], 60)
            
            # Increment hour counter (expires in 3600s)
            pipe.incr(keys["hour"])
            pipe.expire(keys["hour"], 3600)
            
            # Increment day counter (expires in 86400s)
            pipe.incr(keys["day"])
            pipe.expire(keys["day"], 86400)
            
            await pipe.execute()
            
            logger.debug("rate-limit-recorded", api=api_name)
            
        except Exception as e:
            logger.error("rate-limit-record-failed", api=api_name, error=str(e))
    
    async def get_remaining(self, api_name: str) -> Dict[str, int]:
        """
        Get remaining requests for the API.
        
        Args:
            api_name: Name of the API
            
        Returns:
            Dict with remaining requests per window
        """
        config = self.limits.get(api_name)
        if not config:
            return {"minute": 999, "hour": 999, "day": 999}
        
        cache = await self._get_cache()
        if not cache._enabled or not cache._redis:
            return {
                "minute": config.requests_per_minute,
                "hour": config.requests_per_hour,
                "day": config.requests_per_day,
            }
        
        keys = self._get_keys(api_name)
        
        try:
            minute_count = await cache._redis.get(keys["minute"])
            hour_count = await cache._redis.get(keys["hour"])
            day_count = await cache._redis.get(keys["day"])
            
            return {
                "minute": config.requests_per_minute - (int(minute_count) if minute_count else 0),
                "hour": config.requests_per_hour - (int(hour_count) if hour_count else 0),
                "day": config.requests_per_day - (int(day_count) if day_count else 0),
            }
            
        except Exception as e:
            logger.error("rate-limit-get-remaining-failed", api=api_name, error=str(e))
            return {
                "minute": config.requests_per_minute,
                "hour": config.requests_per_hour,
                "day": config.requests_per_day,
            }
    
    async def acquire(self, api_name: str, timeout: float = 5.0):
        """
        Acquire permission to make an API call.
        
        This is an async context manager that:
        1. Checks if request is allowed
        2. Waits if rate limited (up to timeout)
        3. Records the request on success
        
        Usage:
            async with limiter.acquire("google_places"):
                # Make API call
                pass
        
        Args:
            api_name: Name of the API
            timeout: Max seconds to wait if rate limited
            
        Raises:
            RateLimitExceeded: If limit not available within timeout
        """
        return _RateLimitContext(self, api_name, timeout)
    
    async def wait_for_slot(self, api_name: str, timeout: float = 5.0) -> bool:
        """
        Wait for a rate limit slot to become available.
        
        Args:
            api_name: Name of the API
            timeout: Max seconds to wait
            
        Returns:
            True if slot became available, False if timeout
        """
        start = time.time()
        
        while time.time() - start < timeout:
            if await self.is_allowed(api_name):
                return True
            
            # Wait a bit before retrying
            await asyncio.sleep(0.5)
        
        return False


class _RateLimitContext:
    """Context manager for rate-limited API calls."""
    
    def __init__(self, limiter: RateLimiter, api_name: str, timeout: float):
        self.limiter = limiter
        self.api_name = api_name
        self.timeout = timeout
    
    async def __aenter__(self):
        # Wait for slot
        if not await self.limiter.wait_for_slot(self.api_name, self.timeout):
            remaining = await self.limiter.get_remaining(self.api_name)
            # Calculate retry time based on which limit was hit
            retry_after = 60  # Default to 1 minute
            if remaining["minute"] <= 0:
                retry_after = 60
            elif remaining["hour"] <= 0:
                retry_after = 3600
            else:
                retry_after = 86400
            
            raise RateLimitExceeded(self.api_name, retry_after)
        
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        # Only record if no exception (successful call)
        if exc_type is None:
            await self.limiter.record_request(self.api_name)
        
        return False


# Global rate limiter instance
_rate_limiter: Optional[RateLimiter] = None


async def get_rate_limiter() -> RateLimiter:
    """Get or create global rate limiter instance."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter()
    return _rate_limiter

