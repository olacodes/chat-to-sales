"""
Redis-backed cache client.
Used for session state, rate limiting, and short-lived conversation context.
"""

from collections.abc import AsyncGenerator

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)
_settings = get_settings()

_redis_pool: aioredis.Redis | None = None


async def init_redis() -> None:
    global _redis_pool
    _redis_pool = aioredis.from_url(
        _settings.redis_url_str,
        encoding="utf-8",
        decode_responses=True,
    )
    await _redis_pool.ping()
    logger.info("Redis connection established.")


async def close_redis() -> None:
    global _redis_pool
    if _redis_pool:
        await _redis_pool.aclose()
        logger.info("Redis connection closed.")


def get_redis() -> aioredis.Redis:
    if _redis_pool is None:
        raise RuntimeError("Redis not initialised. Call init_redis() on startup.")
    return _redis_pool
