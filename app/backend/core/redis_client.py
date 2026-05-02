import redis.asyncio as redis

from app.backend.core.config import settings


import os

# Use Railway REDIS_URL, no localhost fallback
_redis_url = settings.REDIS_URL or os.getenv("REDIS_URL", "")
if not _redis_url:
    # Do not crash when REDIS_URL missing; operate in degraded mode with redis_client = None
    print("[STARTUP] WARNING: REDIS_URL not set; Redis features will be disabled (degraded mode).")
    redis_client = None
else:
    try:
        redis_client = redis.from_url(
            _redis_url,
            decode_responses=True,
        )
    except Exception as e:
        print(f"[STARTUP] WARNING: Failed to create Redis client: {e}; Redis features disabled.")
        redis_client = None
