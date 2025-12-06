"""Redis cache manager for optimizing repeated queries and reducing API costs."""

import hashlib
import json
from typing import Any, Callable, Optional

import redis.asyncio as redis
from redis.exceptions import RedisError

from src.config.settings import Settings, get_settings
from src.utils.logger import get_logger


class CacheManager:
    """
    Redis-based cache manager with automatic key generation,
    TTL management, and fallback handling.
    """

    def __init__(self, settings: Optional[Settings] = None):
        """Initialize cache manager with Redis connection."""
        self.settings = settings or get_settings()
        self.logger = get_logger("cache_manager")
        self._redis: Optional[redis.Redis] = None
        self._enabled = self.settings.redis_enabled

    async def connect(self) -> None:
        """Establish Redis connection."""
        if not self._enabled:
            self.logger.info("cache_disabled", reason="REDIS_ENABLED=false")
            return

        try:
            self._redis = await redis.from_url(
                self.settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5,
            )
            await self._redis.ping()
            self.logger.info("cache_connected", url=self.settings.redis_url)
        except RedisError as exc:
            self.logger.error("cache_connection_failed", error=str(exc))
            self._enabled = False
            self._redis = None

    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self._redis:
            await self._redis.aclose()
            self.logger.info("cache_disconnected")

    def _generate_key(self, prefix: str, *args: Any, **kwargs: Any) -> str:
        """
        Generate a unique cache key based on prefix and arguments.

        Args:
            prefix: Cache key prefix (e.g., 'intent', 'places', 'translate')
            *args: Positional arguments to hash
            **kwargs: Keyword arguments to hash

        Returns:
            Unique cache key string
        """
        # Combine all arguments into a consistent string
        data = {
            "args": args,
            "kwargs": sorted(kwargs.items()),  # Sort for consistency
        }
        serialized = json.dumps(data, sort_keys=True, default=str)
        hash_value = hashlib.sha256(serialized.encode()).hexdigest()[:16]
        return f"{self.settings.redis_key_prefix}:{prefix}:{hash_value}"

    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found/cache disabled
        """
        if not self._enabled or not self._redis:
            return None

        try:
            value = await self._redis.get(key)
            if value:
                self.logger.debug("cache_hit", key=key)
                return json.loads(value)
            else:
                self.logger.debug("cache_miss", key=key)
                return None
        except (RedisError, json.JSONDecodeError) as exc:
            self.logger.warning("cache_get_error", key=key, error=str(exc))
            return None

    async def set(
        self,
        key: str,
        value: Any,
        ttl: Optional[int] = None,
    ) -> bool:
        """
        Set value in cache with optional TTL.

        Args:
            key: Cache key
            value: Value to cache (must be JSON-serializable)
            ttl: Time to live in seconds (None = no expiration)

        Returns:
            True if successful, False otherwise
        """
        if not self._enabled or not self._redis:
            return False

        try:
            serialized = json.dumps(value, default=str)
            if ttl:
                await self._redis.setex(key, ttl, serialized)
            else:
                await self._redis.set(key, serialized)
            self.logger.debug("cache_set", key=key, ttl=ttl)
            return True
        except (RedisError, TypeError, ValueError) as exc:
            self.logger.warning("cache_set_error", key=key, error=str(exc))
            return False

    async def delete(self, key: str) -> bool:
        """
        Delete key from cache.

        Args:
            key: Cache key

        Returns:
            True if deleted, False otherwise
        """
        if not self._enabled or not self._redis:
            return False

        try:
            result = await self._redis.delete(key)
            self.logger.debug("cache_delete", key=key, deleted=bool(result))
            return bool(result)
        except RedisError as exc:
            self.logger.warning("cache_delete_error", key=key, error=str(exc))
            return False

    async def get_or_set(
        self,
        prefix: str,
        fetch_fn: Callable,
        ttl: Optional[int] = None,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """
        Get value from cache or compute and cache it if not found.

        Args:
            prefix: Cache key prefix
            fetch_fn: Async function to call if cache miss
            ttl: Time to live in seconds
            *args: Arguments for key generation and fetch_fn
            **kwargs: Keyword arguments for key generation and fetch_fn

        Returns:
            Cached or freshly computed value
        """
        key = self._generate_key(prefix, *args, **kwargs)

        # Try to get from cache
        cached = await self.get(key)
        if cached is not None:
            return cached

        # Cache miss - compute value
        try:
            if callable(fetch_fn):
                # Handle both async and sync functions
                if hasattr(fetch_fn, "__call__"):
                    import inspect
                    if inspect.iscoroutinefunction(fetch_fn):
                        value = await fetch_fn(*args, **kwargs)
                    else:
                        value = fetch_fn(*args, **kwargs)
                else:
                    value = await fetch_fn(*args, **kwargs)

                # Cache the result
                await self.set(key, value, ttl)
                return value
        except Exception as exc:
            self.logger.error(
                "cache_fetch_error",
                prefix=prefix,
                error=str(exc),
            )
            raise

    async def invalidate_pattern(self, pattern: str) -> int:
        """
        Invalidate all keys matching a pattern.

        Args:
            pattern: Redis key pattern (e.g., 'intent:*', 'places:user123:*')

        Returns:
            Number of keys deleted
        """
        if not self._enabled or not self._redis:
            return 0

        try:
            keys = []
            async for key in self._redis.scan_iter(match=pattern):
                keys.append(key)

            if keys:
                deleted = await self._redis.delete(*keys)
                self.logger.info(
                    "cache_pattern_invalidated",
                    pattern=pattern,
                    count=deleted,
                )
                return deleted
            return 0
        except RedisError as exc:
            self.logger.warning(
                "cache_invalidate_error",
                pattern=pattern,
                error=str(exc),
            )
            return 0

    async def clear_all(self) -> bool:
        """
        Clear all keys with the configured prefix.

        Returns:
            True if successful
        """
        pattern = f"{self.settings.redis_key_prefix}:*"
        count = await self.invalidate_pattern(pattern)
        return count > 0


# Global cache instance
_cache_instance: Optional[CacheManager] = None


async def get_cache_manager() -> CacheManager:
    """
    Get or create global cache manager instance.

    Returns:
        Singleton CacheManager instance
    """
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CacheManager()
        await _cache_instance.connect()
    return _cache_instance

