import redis.asyncio as redis

from app.backend.core.config import settings


import os

# Use Railway REDIS_URL, no localhost fallback
_redis_url = settings.REDIS_URL or os.getenv("REDIS_URL", "")
if not _redis_url:
    raise ValueError("REDIS_URL must be set in environment")

redis_client = redis.from_url(
    _redis_url,
    decode_responses=True,
)
