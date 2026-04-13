"""
API resilience layer: retry, rate limiting, caching, fallback.

Provides utilities for handling API quotas, failures, and degradation.
"""

import asyncio
import json
import hashlib
import logging
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Optional, TypeVar, Union
from functools import wraps

import redis.asyncio as aioredis
from redis.exceptions import RedisError

from app.backend.core.config import settings

logger = logging.getLogger(__name__)

T = TypeVar("T")


# =====================================================================
# Exponential Backoff Retry
# =====================================================================

class RetryConfig:
    """Configuration for retry strategy."""
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay_seconds: int = 2,
        max_delay_seconds: int = 60,
        exponential_base: float = 2.0,
        jitter: bool = True,
    ):
        self.max_attempts = max_attempts
        self.base_delay_seconds = base_delay_seconds
        self.max_delay_seconds = max_delay_seconds
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for next retry with exponential backoff."""
        delay = self.base_delay_seconds * (self.exponential_base ** attempt)
        delay = min(delay, self.max_delay_seconds)
        
        if self.jitter:
            delay *= (0.5 + random.random())
        
        return delay


async def retry_async(
    func: Callable,
    *args,
    max_attempts: int = 3,
    base_delay_seconds: int = 2,
    max_delay_seconds: int = 60,
    retry_on_exceptions: tuple = (Exception,),
    on_retry: Optional[Callable] = None,
    **kwargs
) -> Any:
    """
    Retry async function with exponential backoff.
    
    Args:
        func: Async function to retry
        max_attempts: Maximum retry attempts
        base_delay_seconds: Initial delay between retries
        max_delay_seconds: Maximum delay between retries
        retry_on_exceptions: Exception types to retry on
        on_retry: Callback function(attempt, exception, delay)
    """
    config = RetryConfig(
        max_attempts=max_attempts,
        base_delay_seconds=base_delay_seconds,
        max_delay_seconds=max_delay_seconds,
    )
    
    last_exception = None
    
    for attempt in range(config.max_attempts):
        try:
            return await func(*args, **kwargs)
        except retry_on_exceptions as e:
            last_exception = e
            
            if attempt < config.max_attempts - 1:
                delay = config.get_delay(attempt)
                logger.warning(
                    f"Attempt {attempt + 1}/{config.max_attempts} failed for {func.__name__}: {e}. "
                    f"Retrying in {delay:.1f}s..."
                )
                
                if on_retry:
                    await on_retry(attempt + 1, e, delay) if asyncio.iscoroutinefunction(on_retry) else on_retry(attempt + 1, e, delay)
                
                await asyncio.sleep(delay)
            else:
                logger.error(
                    f"All {config.max_attempts} attempts failed for {func.__name__}. "
                    f"Last error: {e}"
                )
    
    raise last_exception or Exception(f"Failed after {config.max_attempts} attempts")


# =====================================================================
# Rate Limiting (Redis-based Token Bucket)
# =====================================================================

class RateLimiter:
    """Distributed rate limiter using Redis."""
    
    def __init__(
        self,
        redis_url: str = settings.REDIS_URL,
        default_limit: int = 100,
        default_window_seconds: int = 60,
    ):
        self.redis_url = redis_url
        self.default_limit = default_limit
        self.default_window_seconds = default_window_seconds
        self._client: Optional[aioredis.Redis] = None
        self._loop_id: Optional[int] = None
    
    async def _get_client(self) -> aioredis.Redis:
        """Get or create Redis client."""
        current_loop_id = id(asyncio.get_running_loop())

        if self._client is not None and self._loop_id != current_loop_id:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

        if self._client is None:
            self._client = await aioredis.from_url(self.redis_url, decode_responses=True)
            self._loop_id = current_loop_id
        return self._client
    
    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._loop_id = None
    
    async def is_allowed(
        self,
        identifier: str,
        limit: int = None,
        window_seconds: int = None,
    ) -> bool:
        """
        Check if request is allowed under rate limit.
        Uses token bucket algorithm.
        """
        limit = limit or self.default_limit
        window_seconds = window_seconds or self.default_window_seconds
        
        try:
            client = await self._get_client()
            key = f"ratelimit:{identifier}"
            
            # Get current count
            current = await client.get(key)
            current_count = int(current) if current else 0
            
            if current_count < limit:
                # Increment and set TTL
                new_count = await client.incr(key)
                if new_count == 1:
                    await client.expire(key, window_seconds)
                return True
            else:
                logger.warning(f"Rate limit exceeded for {identifier}: {current_count}/{limit}")
                return False
        
        except RedisError as e:
            logger.error(f"Redis error in rate limiter: {e}")
            # Fail open on Redis errors
            return True
    
    async def get_remaining(
        self,
        identifier: str,
        limit: int = None,
    ) -> int:
        """Get remaining requests in current window."""
        limit = limit or self.default_limit
        
        try:
            client = await self._get_client()
            key = f"ratelimit:{identifier}"
            current = await client.get(key)
            current_count = int(current) if current else 0
            return max(0, limit - current_count)
        except RedisError:
            return limit


# Global rate limiter instances
_news_api_limiter = RateLimiter(default_limit=20, default_window_seconds=60)
_llm_limiter = RateLimiter(default_limit=5, default_window_seconds=60)


async def check_rate_limit(
    identifier: str,
    limiter: RateLimiter = None,
    limit: int = None,
    window_seconds: int = 60,
) -> bool:
    """Check if request is allowed."""
    limiter = limiter or _news_api_limiter
    return await limiter.is_allowed(identifier, limit=limit, window_seconds=window_seconds)


# =====================================================================
# Redis Caching with TTL
# =====================================================================

class CacheManager:
    """Redis-based cache with TTL support."""
    
    def __init__(self, redis_url: str = settings.REDIS_URL):
        self.redis_url = redis_url
        self._client: Optional[aioredis.Redis] = None
        self._loop_id: Optional[int] = None
    
    async def _get_client(self) -> aioredis.Redis:
        """Get or create Redis client."""
        current_loop_id = id(asyncio.get_running_loop())

        if self._client is not None and self._loop_id != current_loop_id:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None

        if self._client is None:
            self._client = await aioredis.from_url(self.redis_url, decode_responses=True)
            self._loop_id = current_loop_id
        return self._client
    
    async def close(self):
        """Close Redis connection."""
        if self._client:
            await self._client.aclose()
            self._client = None
            self._loop_id = None
    
    @staticmethod
    def _make_key(namespace: str, *args) -> str:
        """Generate cache key."""
        key_parts = [namespace] + [str(arg) for arg in args]
        payload = ":".join(key_parts)
        return f"cache:{hashlib.md5(payload.encode()).hexdigest()}"
    
    async def get(self, namespace: str, *args) -> Optional[Any]:
        """Get value from cache."""
        try:
            client = await self._get_client()
            key = self._make_key(namespace, *args)
            value = await client.get(key)
            
            if value:
                try:
                    return json.loads(value)
                except json.JSONDecodeError:
                    return value
            return None
        except RedisError as e:
            logger.warning(f"Cache get error: {e}")
            return None
    
    async def set(
        self,
        namespace: str,
        ttl_hours: int,
        value: Any,
        *args,
    ) -> bool:
        """Set value in cache with TTL."""
        try:
            client = await self._get_client()
            key = self._make_key(namespace, *args)
            
            if isinstance(value, (dict, list)):
                value = json.dumps(value)
            
            ttl_seconds = ttl_hours * 3600
            await client.setex(key, ttl_seconds, str(value))
            return True
        
        except RedisError as e:
            logger.warning(f"Cache set error: {e}")
            return False
    
    async def delete(self, namespace: str, *args) -> bool:
        """Delete value from cache."""
        try:
            client = await self._get_client()
            key = self._make_key(namespace, *args)
            await client.delete(key)
            return True
        except RedisError:
            return False


# Global cache manager
_cache_manager = CacheManager()


async def cache_get(namespace: str, *args) -> Optional[Any]:
    """Get from cache."""
    return await _cache_manager.get(namespace, *args)


async def cache_set(
    namespace: str,
    ttl_hours: int,
    value: Any,
    *args,
) -> bool:
    """Set cache value."""
    return await _cache_manager.set(namespace, ttl_hours, value, *args)


async def cache_delete(namespace: str, *args) -> bool:
    """Delete from cache."""
    return await _cache_manager.delete(namespace, *args)


# =====================================================================
# Fallback & Degradation
# =====================================================================

class FallbackHandler:
    """Fallback strategy for API failures."""
    
    def __init__(
        self,
        primary_fn: Callable,
        fallback_fn: Optional[Callable] = None,
        use_cache_on_failure: bool = True,
        cache_namespace: str = "fallback",
    ):
        self.primary_fn = primary_fn
        self.fallback_fn = fallback_fn
        self.use_cache_on_failure = use_cache_on_failure
        self.cache_namespace = cache_namespace
    
    async def execute(
        self,
        *args,
        cache_key_args: Optional[tuple] = None,
        **kwargs
    ) -> Optional[Any]:
        """
        Execute with fallback strategy:
        1. Try primary function
        2. If fails and fallback_fn exists, try it
        3. If still fails and use_cache_on_failure, return cached value
        """
        cache_key_args = cache_key_args or args[:2] if len(args) >= 2 else (str(args),)
        
        try:
            logger.info(f"Executing primary: {self.primary_fn.__name__}")
            result = await self.primary_fn(*args, **kwargs)
            
            # Cache success
            await cache_set(
                self.cache_namespace,
                24,  # 24h default
                result,
                *cache_key_args,
            )
            return result
        
        except Exception as e:
            logger.warning(f"Primary failed ({self.primary_fn.__name__}): {e}")
            
            # Try fallback
            if self.fallback_fn:
                try:
                    logger.info(f"Executing fallback: {self.fallback_fn.__name__}")
                    result = await self.fallback_fn(*args, **kwargs)
                    return result
                except Exception as e2:
                    logger.warning(f"Fallback failed ({self.fallback_fn.__name__}): {e2}")
            
            # Return cached value if available
            if self.use_cache_on_failure:
                cached = await cache_get(self.cache_namespace, *cache_key_args)
                if cached is not None:
                    logger.info(f"Returning cached value for {self.cache_namespace}")
                    return cached
            
            raise


# =====================================================================
# Decorators
# =====================================================================

def with_retry(
    max_attempts: int = 3,
    base_delay_seconds: int = 2,
    max_delay_seconds: int = 60,
):
    """Decorator for async function retry."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_async(
                func,
                *args,
                max_attempts=max_attempts,
                base_delay_seconds=base_delay_seconds,
                max_delay_seconds=max_delay_seconds,
                **kwargs,
            )
        return wrapper
    return decorator


def with_cache(namespace: str, ttl_hours: int = 24):
    """Decorator for caching async function results."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            # Try cache first
            cached = await cache_get(namespace, *args)
            if cached is not None:
                logger.debug(f"Cache hit for {namespace}/{args}")
                return cached
            
            # Execute function
            result = await func(*args, **kwargs)
            
            # Store in cache
            await cache_set(namespace, ttl_hours, result, *args)
            return result
        
        return wrapper
    return decorator


async def shutdown_resilience():
    """Cleanup resilience resources."""
    try:
        await _cache_manager.close()
        await _news_api_limiter.close()
        await _llm_limiter.close()
        logger.info("Resilience services shut down")
    except Exception as e:
        logger.error(f"Error shutting down resilience: {e}")
