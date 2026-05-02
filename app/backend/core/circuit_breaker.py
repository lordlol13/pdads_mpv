"""
Circuit breaker pattern for external API resilience.

Prevents cascading failures by temporarily disabling calls to failing services.
"""

import logging
import time
from enum import Enum
from typing import Callable, TypeVar, Any
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar("T")


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing if recovered


class CircuitBreaker:
    """Circuit breaker for protecting external API calls."""

    def __init__(
        self,
        name: str,
        fail_threshold: int = 5,
        recovery_timeout: float = 30.0,
        half_open_max_calls: int = 3,
    ):
        self.name = name
        self.fail_threshold = fail_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._fail_count = 0
        self._success_count = 0
        self._last_failure_time: float = 0.0
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        """Get current circuit state."""
        if self._state == CircuitState.OPEN:
            # Check if we should try half-open
            if time.time() - self._last_failure_time > self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("[CIRCUIT BREAKER] %s entering HALF_OPEN state", self.name)
        return self._state

    def record_success(self):
        """Record a successful call."""
        if self._state == CircuitState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.half_open_max_calls:
                self._state = CircuitState.CLOSED
                self._fail_count = 0
                self._success_count = 0
                logger.info("[CIRCUIT BREAKER] %s closed after recovery", self.name)
        elif self._state == CircuitState.CLOSED:
            self._fail_count = max(0, self._fail_count - 1)

    def record_failure(self):
        """Record a failed call."""
        self._fail_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.OPEN
            logger.error("[CIRCUIT BREAKER] %s re-opened due to failure", self.name)
        elif self._state == CircuitState.CLOSED and self._fail_count >= self.fail_threshold:
            self._state = CircuitState.OPEN
            logger.error(
                "[CIRCUIT BREAKER] %s opened after %d failures",
                self.name, self._fail_count
            )

    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function with circuit breaker protection."""
        current_state = self.state

        if current_state == CircuitState.OPEN:
            raise CircuitBreakerOpen(f"Circuit breaker {self.name} is OPEN")

        if current_state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls > self.half_open_max_calls:
                raise CircuitBreakerOpen(f"Circuit breaker {self.name} half-open limit reached")

        try:
            result = func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise

    async def call_async(self, func: Callable[..., Any], *args, **kwargs) -> Any:
        """Execute async function with circuit breaker protection."""
        current_state = self.state

        if current_state == CircuitState.OPEN:
            raise CircuitBreakerOpen(f"Circuit breaker {self.name} is OPEN")

        if current_state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls > self.half_open_max_calls:
                raise CircuitBreakerOpen(f"Circuit breaker {self.name} half-open limit reached")

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except Exception as e:
            self.record_failure()
            raise


class CircuitBreakerOpen(Exception):
    """Exception raised when circuit breaker is open."""
    pass


# Global circuit breakers for external services
_news_api_breaker = CircuitBreaker("news_api", fail_threshold=5, recovery_timeout=60.0)
_llm_api_breaker = CircuitBreaker("llm_api", fail_threshold=3, recovery_timeout=30.0)
_email_breaker = CircuitBreaker("email", fail_threshold=5, recovery_timeout=30.0)


def get_breaker(name: str) -> CircuitBreaker:
    """Get circuit breaker by name."""
    breakers = {
        "news_api": _news_api_breaker,
        "llm_api": _llm_api_breaker,
        "email": _email_breaker,
    }
    return breakers.get(name, CircuitBreaker(name))


def circuit_breaker_protected(breaker_name: str):
    """Decorator to protect function with circuit breaker."""
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            breaker = get_breaker(breaker_name)
            return breaker.call(func, *args, **kwargs)
        return wrapper
    return decorator
