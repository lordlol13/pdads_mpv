"""
Tests for API resilience layer (retry, rate limiting, caching, fallback).
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.backend.services.resilience_service import (
    RetryConfig,
    retry_async,
    RateLimiter,
    CacheManager,
    FallbackHandler,
    with_retry,
    with_cache,
)


class TestRetryConfig:
    """Test exponential backoff retry configuration."""
    
    def test_delay_increases_exponentially(self):
        config = RetryConfig(
            max_attempts=5,
            base_delay_seconds=1,
            max_delay_seconds=60,
            exponential_base=2.0,
            jitter=False,  # Disable jitter for predictable tests
        )
        
        # Delays should double each time: 1, 2, 4, 8, 16...
        assert config.get_delay(0) == 1
        assert config.get_delay(1) == 2
        assert config.get_delay(2) == 4
        assert config.get_delay(3) == 8
        assert config.get_delay(4) == 16
    
    def test_delay_respects_max(self):
        config = RetryConfig(
            max_attempts=10,
            base_delay_seconds=10,
            max_delay_seconds=30,
            exponential_base=2.0,
            jitter=False,
        )
        
        # Should cap at max_delay_seconds
        delay_5 = config.get_delay(5)  # 10 * 2^5 = 320, but capped at 30
        assert delay_5 == 30
    
    def test_jitter_adds_randomness(self):
        config = RetryConfig(
            max_attempts=5,
            base_delay_seconds=10,
            max_delay_seconds=100,
            exponential_base=2.0,
            jitter=True,
        )
        
        # With jitter, delays should vary
        delays = [config.get_delay(2) for _ in range(5)]
        assert len(set(delays)) > 1  # Should have variation


@pytest.mark.asyncio
class TestRetryAsync:
    """Test async retry logic."""
    
    async def test_success_on_first_try(self):
        mock_fn = AsyncMock(return_value="success")
        
        result = await retry_async(
            mock_fn,
            max_attempts=3,
        )
        
        assert result == "success"
        assert mock_fn.call_count == 1
    
    async def test_retries_on_failure_then_succeeds(self):
        mock_fn = AsyncMock(
            side_effect=[
                Exception("attempt 1 failed"),
                Exception("attempt 2 failed"),
                "success",
            ]
        )
        
        result = await retry_async(
            mock_fn,
            max_attempts=3,
            base_delay_seconds=0.01,  # Short delay for testing
        )
        
        assert result == "success"
        assert mock_fn.call_count == 3
    
    async def test_raises_after_max_attempts(self):
        mock_fn = AsyncMock(side_effect=ValueError("always fails"))
        
        with pytest.raises(ValueError, match="always fails"):
            await retry_async(
                mock_fn,
                max_attempts=2,
                base_delay_seconds=0.01,
            )
        
        assert mock_fn.call_count == 2
    
    async def test_retry_on_specific_exceptions_only(self):
        """Should only retry on specified exceptions."""
        mock_fn = AsyncMock(side_effect=RuntimeError("should not retry"))
        
        with pytest.raises(RuntimeError):
            await retry_async(
                mock_fn,
                max_attempts=3,
                retry_on_exceptions=(ValueError,),  # Only retry on ValueError
            )
        
        # Should fail immediately without retries
        assert mock_fn.call_count == 1


@pytest.mark.asyncio
class TestRateLimiter:
    """Test rate limiting with Redis."""
    
    @pytest.mark.skip(reason="Requires Redis connection")
    async def test_allows_requests_within_limit(self):
        limiter = RateLimiter(default_limit=5, default_window_seconds=60)
        
        # First 5 should be allowed
        for i in range(5):
            allowed = await limiter.is_allowed(f"test_key_{i}", limit=5)
            assert allowed
        
        await limiter.close()
    
    @pytest.mark.skip(reason="Requires Redis connection")
    async def test_blocks_requests_over_limit(self):
        limiter = RateLimiter(default_limit=3, default_window_seconds=60)
        
        # Allow 3 requests
        for i in range(3):
            allowed = await limiter.is_allowed("test_key", limit=3)
            assert allowed
        
        # 4th should fail
        allowed = await limiter.is_allowed("test_key", limit=3)
        assert not allowed
        
        await limiter.close()


@pytest.mark.asyncio
class TestCacheManager:
    """Test caching with TTL."""
    
    @pytest.mark.skip(reason="Requires Redis connection")
    async def test_cache_set_and_get(self):
        cache = CacheManager()
        
        value = {"key": "value", "number": 42}
        await cache.set("test_namespace", 1, value, "arg1", "arg2")
        
        retrieved = await cache.get("test_namespace", "arg1", "arg2")
        assert retrieved == value
        
        await cache.close()
    
    @pytest.mark.skip(reason="Requires Redis connection")
    async def test_cache_expiry(self):
        cache = CacheManager()
        
        value = "test_value"
        await cache.set("test_namespace", 0.01, value, "key1")  # 0.01 hour = very short TTL
        
        retrieved = await cache.get("test_namespace", "key1")
        assert retrieved == value
        
        # Wait for expiry
        await asyncio.sleep(0.1)
        
        expired = await cache.get("test_namespace", "key1")
        assert expired is None
        
        await cache.close()
    
    def test_make_key_consistency(self):
        """Test that cache keys are deterministic."""
        key1 = CacheManager._make_key("namespace", "arg1", "arg2")
        key2 = CacheManager._make_key("namespace", "arg1", "arg2")
        key3 = CacheManager._make_key("namespace", "arg1", "arg3")
        
        assert key1 == key2
        assert key1 != key3


@pytest.mark.asyncio
class TestFallbackHandler:
    """Test fallback and degradation strategy."""
    
    async def test_primary_success_no_fallback_needed(self):
        primary = AsyncMock(return_value="primary_success")
        fallback = AsyncMock(return_value="fallback_result")
        
        handler = FallbackHandler(primary, fallback)
        result = await handler.execute("arg1", "arg2")
        
        assert result == "primary_success"
        assert primary.call_count == 1
        assert fallback.call_count == 0
    
    async def test_primary_fails_fallback_succeeds(self):
        primary = AsyncMock(side_effect=Exception("primary failed"))
        fallback = AsyncMock(return_value="fallback_success")
        
        handler = FallbackHandler(primary, fallback)
        result = await handler.execute("arg1", "arg2")
        
        assert result == "fallback_success"
        assert primary.call_count == 1
        assert fallback.call_count == 1
    
    async def test_both_fail_returns_none(self):
        primary = AsyncMock(side_effect=Exception("primary failed"))
        fallback = AsyncMock(side_effect=Exception("fallback failed"))
        
        handler = FallbackHandler(
            primary,
            fallback,
            use_cache_on_failure=False,  # Disable cache for this test
        )
        
        with pytest.raises(Exception):
            await handler.execute("arg1", "arg2")
        
        assert primary.call_count == 1
        assert fallback.call_count == 1


class TestDecorators:
    """Test decorator utilities."""
    
    @pytest.mark.asyncio
    async def test_with_retry_decorator(self):
        """Test @with_retry decorator."""
        call_count = 0
        
        @with_retry(max_attempts=3, base_delay_seconds=0.01)
        async def failing_then_succeeds():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError(f"Call {call_count}")
            return "success"
        
        result = await failing_then_succeeds()
        assert result == "success"
        assert call_count == 3
    
    @pytest.mark.asyncio
    @pytest.mark.skip(reason="Requires Redis connection")
    async def test_with_cache_decorator(self):
        """Test @with_cache decorator."""
        call_count = 0
        
        @with_cache("test_cache", ttl_hours=1)
        async def expensive_operation(arg1, arg2):
            nonlocal call_count
            call_count += 1
            return f"result_{arg1}_{arg2}_{call_count}"
        
        # First call - should execute
        result1 = await expensive_operation("a", "b")
        assert call_count == 1
        
        # Second call - should use cache
        result2 = await expensive_operation("a", "b")
        assert call_count == 1  # Not incremented
        assert result1 == result2


class TestIntegration:
    """Integration tests combining multiple resilience features."""
    
    @pytest.mark.asyncio
    async def test_retry_with_eventual_success(self):
        """Simulate API transient failure + recovery."""
        call_count = 0
        
        async def flaky_api():
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ConnectionError(f"Transient failure #{call_count}")
            return {"status": "success", "data": "important"}
        
        result = await retry_async(
            flaky_api,
            max_attempts=5,
            base_delay_seconds=0.01,
        )
        
        assert result["status"] == "success"
        assert call_count == 3  # Took 3 attempts to succeed
