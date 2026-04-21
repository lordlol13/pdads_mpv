import redis.asyncio as redis

from app.backend.core.config import settings


redis_client = redis.from_url(
    settings.REDIS_URL or "redis://localhost:6379",
    decode_responses=True,
)
