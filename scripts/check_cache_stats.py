#!/usr/bin/env python3
"""Script to check Redis cache statistics and keys."""

import asyncio
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.utils.cache_manager import get_cache_manager
from src.utils.logger import get_logger

logger = get_logger("cache_stats")


async def main():
    """Check Redis cache statistics."""
    cache = await get_cache_manager()
    
    if not cache._enabled or not cache._redis:
        print("❌ Redis is not enabled or not connected")
        return
    
    print("✅ Connected to Redis")
    print(f"📊 Cache prefix: {cache.settings.redis_key_prefix}")
    print()
    
    # Get all keys with our prefix
    pattern = f"{cache.settings.redis_key_prefix}:*"
    keys = []
    async for key in cache._redis.scan_iter(match=pattern):
        keys.append(key)
    
    print(f"🔑 Total cached keys: {len(keys)}")
    print()
    
    # Group by type
    key_types = {}
    for key in keys:
        # Extract type from key (format: prefix:type:hash)
        parts = key.split(":")
        if len(parts) >= 3:
            key_type = parts[2]  # agent:type:hash
            key_types[key_type] = key_types.get(key_type, 0) + 1
    
    if key_types:
        print("📋 Keys by type:")
        for key_type, count in sorted(key_types.items(), key=lambda x: x[1], reverse=True):
            print(f"  • {key_type}: {count}")
        print()
    
    # Show some sample keys
    if keys:
        print("🔍 Sample cached keys (first 10):")
        for key in sorted(keys)[:10]:
            # Get TTL
            ttl = await cache._redis.ttl(key)
            ttl_str = f"{ttl}s" if ttl > 0 else "no expiry" if ttl == -1 else "expired"
            print(f"  • {key} (TTL: {ttl_str})")
        print()
    
    # Show memory usage
    info = await cache._redis.info("memory")
    used_memory = info.get("used_memory_human", "N/A")
    print(f"💾 Redis memory usage: {used_memory}")
    
    await cache.disconnect()


if __name__ == "__main__":
    asyncio.run(main())

