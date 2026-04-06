from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from typing import Any

import redis.asyncio as redis
from redis.exceptions import RedisError

from app.backend.core.config import settings


def _redis_client() -> redis.Redis:
    return redis.from_url(settings.REDIS_URL, decode_responses=True)


def build_cache_key(prefix: str, payload: dict[str, Any]) -> str:
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    digest = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    return f"{prefix}:{digest}"


def _serialize_cache_value(value: dict[str, Any]) -> str:
    return json.dumps(value, ensure_ascii=False)


async def get_or_set_json(
    key: str,
    ttl_seconds: int,
    fetcher: Callable[[], Awaitable[dict[str, Any]]],
) -> dict[str, Any]:
    client = _redis_client()
    try:
        cached = await client.get(key)
        if cached:
            try:
                parsed = json.loads(cached)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                # Malformed cache payload should not break request flow.
                await client.delete(key)

        value = await fetcher()
        await client.set(key, _serialize_cache_value(value), ex=ttl_seconds)
        return value
    except RedisError:
        # Redis is optional for local MVP. Fall back to direct fetch without caching.
        return await fetcher()
    finally:
        await client.aclose()
