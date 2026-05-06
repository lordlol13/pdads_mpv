"""
Health checks and monitoring endpoints for service observability.

Reports on database, cache, external services, and task queues.
"""

import asyncio
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import text

from app.backend.core.config import settings
from app.backend.db import session as db_session
from app.backend.services.resilience_service import _cache_manager, _news_api_limiter
import logging
import os

logger = logging.getLogger(__name__)

# PRODUCTION: External webhook alerting
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "").strip() or None

def _log_task_error(task: asyncio.Task) -> None:
    """Log task exception safely — senior+ level safety."""
    try:
        exc = task.exception()
        if exc:
            logger.error(f"[WEBHOOK ERROR] {exc}")
    except Exception:
        logger.exception("[WEBHOOK ERROR] failed to retrieve exception")


def _safe_fire_and_forget(coro) -> None:
    """Safely schedule async task with exception logging — never crashes app."""
    try:
        task = asyncio.create_task(coro)
        task.add_done_callback(_log_task_error)
    except RuntimeError:
        logger.warning("[WEBHOOK] Event loop not available, skipping alert")


async def _send_degraded_alert(reasons: list[str], timestamp: str) -> None:
    """Send degraded alert to external webhook — fire-and-forget, never blocks."""
    if not ALERT_WEBHOOK_URL:
        return  # No webhook configured, skip silently
    try:
        import httpx
        async with httpx.AsyncClient(timeout=3.0) as client:
            await client.post(
                ALERT_WEBHOOK_URL,
                json={
                    "status": "degraded",
                    "reasons": reasons,
                    "timestamp": timestamp,
                    "service": "news-ai-backend",
                },
            )
    except Exception as e:
        # FAIL-SAFE: Ignore webhook failures, never break main app
        logger.debug(f"[ALERT] Webhook send failed (ignored): {e}")

# PRODUCTION: Global degraded mode tracking
_system_degraded = False
_degraded_reasons: list[str] = []
_degraded_since: datetime | None = None

def set_degraded_mode(reason: str) -> None:
    """Mark system as degraded with specific reason — logs CRITICAL and sends webhook."""
    global _system_degraded, _degraded_reasons, _degraded_since
    _system_degraded = True
    if reason not in _degraded_reasons:
        _degraded_reasons.append(reason)
        if _degraded_since is None:
            _degraded_since = datetime.now(timezone.utc)
        timestamp = _degraded_since.isoformat()
        # PRODUCTION ALERT: CRITICAL log with timestamp
        logger.critical(
            "[ALERT] System entered DEGRADED mode: reason=%s, timestamp=%s, all_reasons=%s",
            reason,
            timestamp,
            _degraded_reasons
        )
        # PRODUCTION: Send external webhook alert (fire-and-forget, safe)
        _safe_fire_and_forget(_send_degraded_alert(_degraded_reasons.copy(), timestamp))

def is_degraded() -> bool:
    """Check if system is in degraded mode."""
    return _system_degraded

def get_degraded_reasons() -> list[str]:
    """Get list of degradation reasons."""
    return _degraded_reasons.copy()

def get_degraded_since() -> datetime | None:
    """Get timestamp when system first entered degraded mode."""
    return _degraded_since


class HealthStatus(str, Enum):
    """Health status indicator."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"


class ComponentHealth(BaseModel):
    """Health status of a single component."""
    name: str
    status: HealthStatus
    message: str
    response_time_ms: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)


class SystemHealth(BaseModel):
    """Overall system health status."""
    status: HealthStatus
    timestamp: datetime
    version: str
    components: list[ComponentHealth]

    # Uptime info
    environment: str

    # PRODUCTION: Degraded mode visibility
    degraded_reasons: list[str] = Field(default_factory=list)
    degraded_since: str | None = None
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "status": "healthy",
                "timestamp": "2026-04-10T12:00:00Z",
                "version": "0.1.0",
                "environment": "development",
                "components": [
                    {
                        "name": "database",
                        "status": "healthy",
                        "message": "PostgreSQL connection OK",
                        "response_time_ms": 5.2,
                    }
                ],
            }
        }
    )


async def check_database_health() -> ComponentHealth:
    """Check database connectivity — handles degraded mode."""
    start = datetime.now()
    # PRODUCTION FIX: Handle None engine (degraded mode)
    if db_session.engine is None or db_session.SessionLocal is None:
        return ComponentHealth(
            name="database",
            status=HealthStatus.DEGRADED,  # Degraded, not unhealthy
            message="Database unavailable — system in degraded mode",
            response_time_ms=0.0,
            details={"degraded": True, "reason": "DATABASE_URL not configured or invalid"},
        )
    try:
        async with db_session.SessionLocal() as session:
            await session.execute(text("SELECT 1"))
        response_time = (datetime.now() - start).total_seconds() * 1000
        return ComponentHealth(
            name="database",
            status=HealthStatus.HEALTHY,
            message="Database connection OK",
            response_time_ms=response_time,
        )
    except Exception as e:
        response_time = (datetime.now() - start).total_seconds() * 1000
        return ComponentHealth(
            name="database",
            status=HealthStatus.UNHEALTHY,
            message=f"Database error: {str(e)}",
            response_time_ms=response_time,
            details={"error": str(e)[:100]},
        )


async def check_redis_health() -> ComponentHealth:
    """Check Redis connectivity."""
    start = datetime.now()
    try:
        client = await _cache_manager._get_client()
        
        # Ping Redis
        pong = await client.ping()
        if not pong:
            raise Exception("PING returned False")
        
        response_time = (datetime.now() - start).total_seconds() * 1000
        return ComponentHealth(
            name="redis",
            status=HealthStatus.HEALTHY,
            message="Redis connection OK",
            response_time_ms=response_time,
        )
    except Exception as e:
        response_time = (datetime.now() - start).total_seconds() * 1000
        return ComponentHealth(
            name="redis",
            status=HealthStatus.DEGRADED,
            message=f"Redis unavailable: {str(e)}",
            response_time_ms=response_time,
            details={"error": str(e)[:100]},
        )


async def check_news_api_health() -> ComponentHealth:
    """Check News API configuration and basic connectivity."""
    start = datetime.now()
    try:
        if not settings.NEWS_API_KEY:
            raise ValueError("NEWS_API_KEY not configured")
        
        # Check rate limiter
        remaining = await _news_api_limiter.get_remaining(
            "health_check",
            limit=settings.NEWS_API_RATE_LIMIT_PER_MINUTE,
        )
        
        response_time = (datetime.now() - start).total_seconds() * 1000
        return ComponentHealth(
            name="news_api",
            status=HealthStatus.HEALTHY,
            message=f"News API configured, {remaining} requests remaining this minute",
            response_time_ms=response_time,
            details={"remaining": remaining},
        )
    except Exception as e:
        response_time = (datetime.now() - start).total_seconds() * 1000
        return ComponentHealth(
            name="news_api",
            status=HealthStatus.DEGRADED,
            message=f"News API issue: {str(e)}",
            response_time_ms=response_time,
            details={"error": str(e)[:100]},
        )


async def check_llm_health() -> ComponentHealth:
    """Check LLM service configuration."""
    start = datetime.now()
    try:
        if not settings.GEMINI_API_KEY and not settings.DEEPSEEK_API_KEY:
            raise ValueError("No LLM API keys configured")
        
        primary = "Gemini" if settings.GEMINI_API_KEY else "DeepSeek"
        fallback = "DeepSeek" if settings.DEEPSEEK_API_KEY and primary != "DeepSeek" else None
        
        response_time = (datetime.now() - start).total_seconds() * 1000
        msg = f"LLM configured: primary={primary}"
        if fallback:
            msg += f", fallback={fallback}"
        
        return ComponentHealth(
            name="llm_service",
            status=HealthStatus.HEALTHY,
            message=msg,
            response_time_ms=response_time,
            details={
                "primary": primary,
                "fallback": fallback,
                "fallback_enabled": settings.LLM_FALLBACK_ENABLED,
            },
        )
    except Exception as e:
        response_time = (datetime.now() - start).total_seconds() * 1000
        return ComponentHealth(
            name="llm_service",
            status=HealthStatus.DEGRADED,
            message=f"LLM configuration issue: {str(e)}",
            response_time_ms=response_time,
            details={"error": str(e)[:100]},
        )


async def check_parser_health() -> ComponentHealth:
    """Check when parser last ran and report status.

    - healthy: last run within Scheduler interval * 2
    - degraded: within * 3
    - unhealthy: older than * 3
    """
    start = datetime.now()
    try:
        async with db_session.SessionLocal() as session:
            result = await session.execute(
                text("SELECT last_parsed_at FROM system_state WHERE name = :name"),
                {"name": "parser"},
            )
            last = result.scalar_one_or_none()

        response_time = (datetime.now() - start).total_seconds() * 1000

        if not last:
            return ComponentHealth(
                name="parser",
                status=HealthStatus.DEGRADED,
                message="Parser has not reported a last run",
                response_time_ms=response_time,
            )

        # Normalize timezone
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)

        now = datetime.now(timezone.utc)
        age = now - last
        base = timedelta(minutes=max(1, settings.SCHEDULER_INTERVAL_MINUTES))

        if age <= base * 2:
            status = HealthStatus.HEALTHY
            msg = f"Parser last run {age} ago"
        elif age <= base * 3:
            status = HealthStatus.DEGRADED
            msg = f"Parser last run {age} ago (delayed)"
        else:
            status = HealthStatus.UNHEALTHY
            msg = f"Parser last run {age} ago (stale)"

        return ComponentHealth(
            name="parser",
            status=status,
            message=msg,
            response_time_ms=response_time,
            details={"last_parsed_at": str(last)},
        )
    except Exception as e:
        response_time = (datetime.now() - start).total_seconds() * 1000
        return ComponentHealth(
            name="parser",
            status=HealthStatus.DEGRADED,
            message=f"Parser health check failed: {str(e)}",
            response_time_ms=response_time,
            details={"error": str(e)[:100]},
        )


async def get_system_health() -> SystemHealth:
    """Get overall system health."""
    # Run health checks in parallel
    components = await asyncio.gather(
        check_database_health(),
        check_redis_health(),
        check_news_api_health(),
        check_llm_health(),
        check_parser_health(),
    )
    
    # Determine overall status
    has_unhealthy = any(c.status == HealthStatus.UNHEALTHY for c in components)
    has_degraded = any(c.status == HealthStatus.DEGRADED for c in components)
    
    if has_unhealthy:
        overall_status = HealthStatus.UNHEALTHY
    elif has_degraded:
        overall_status = HealthStatus.DEGRADED
    else:
        overall_status = HealthStatus.HEALTHY
    
    # PRODUCTION: Include degraded mode info in health response
    degraded_reasons_list = get_degraded_reasons()
    degraded_since_dt = get_degraded_since()

    return SystemHealth(
        status=overall_status,
        timestamp=datetime.now(timezone.utc),
        version="0.1.0",
        environment=settings.APP_ENV,
        components=components,
        degraded_reasons=degraded_reasons_list,
        degraded_since=degraded_since_dt.isoformat() if degraded_since_dt else None,
    )


class MetricsData(BaseModel):
    """Application metrics snapshot."""
    uptime_seconds: float
    total_requests: int
    errors_last_hour: int
    cache_hit_rate: float
    rate_limits_triggered: int
    
    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "uptime_seconds": 3600.0,
                "total_requests": 1250,
                "errors_last_hour": 3,
                "cache_hit_rate": 0.65,
                "rate_limits_triggered": 1,
            }
        }
    )


class RecommendationMetrics(BaseModel):
    """Recommendation quality and engagement metrics."""

    timeframe_hours: int
    impressions: int
    viewed_clicks: int
    ctr: float
    avg_time_spent_seconds: float
    positive_engagements: int
    recommendation_accuracy: float


class PipelineMetrics(BaseModel):
    """Pipeline reliability and performance metrics."""

    timeframe_hours: int
    total_raw_news: int
    completed_jobs: int
    failed_jobs: int
    pending_jobs: int
    retry_count: int
    avg_attempt_count: float
    avg_processing_latency_seconds: float


class ExtendedMetricsData(MetricsData):
    """Application metrics with recommendation and pipeline observability."""

    recommendation: RecommendationMetrics
    pipeline: PipelineMetrics


_start_time: datetime = datetime.now(timezone.utc)


def get_uptime_seconds() -> float:
    """Get application uptime in seconds."""
    return (datetime.now(timezone.utc) - _start_time).total_seconds()


# Placeholder for metrics collection
# In production, use Prometheus or similar
class MetricsCollector:
    """Simple metrics collector with error rate tracking."""

    def __init__(self):
        self.total_requests = 0
        self.total_errors = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.rate_limit_hits = 0
        self._error_window: list[tuple[datetime, str]] = []  # (timestamp, error_type)
        self._window_size = 100  # Keep last 100 errors

    def record_request(self, is_error: bool = False):
        self.total_requests += 1
        if is_error:
            self.total_errors += 1

    def record_error(self, error_type: str = "general"):
        """Record error for error rate tracking."""
        self.total_errors += 1
        now = datetime.now(timezone.utc)
        self._error_window.append((now, error_type))
        # Keep only last N errors
        if len(self._error_window) > self._window_size:
            self._error_window = self._error_window[-self._window_size:]

    def get_error_rate(self, window_seconds: int = 300) -> float:
        """Calculate error rate over the specified window."""
        if self.total_requests == 0:
            return 0.0
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        recent_errors = sum(1 for ts, _ in self._error_window if ts > cutoff)
        # Approximate: use total requests as denominator
        return min(recent_errors / max(self.total_requests, 1), 1.0)

    def check_error_rate_threshold(self) -> bool:
        """Check if error rate exceeds threshold for degraded mode."""
        error_rate = self.get_error_rate()
        if error_rate > settings.ERROR_RATE_THRESHOLD:
            logger.error(
                "[SYSTEM DEGRADED] Error rate %.2f%% exceeds threshold %.2f%%",
                error_rate * 100,
                settings.ERROR_RATE_THRESHOLD * 100
            )
            set_degraded_mode(f"High error rate: {error_rate:.1%}")
            return True
        return False

    def record_cache_hit(self):
        self.cache_hits += 1

    def record_cache_miss(self):
        self.cache_misses += 1

    def record_rate_limit(self):
        self.rate_limit_hits += 1

    def get_metrics(self) -> MetricsData:
        total_cache = self.cache_hits + self.cache_misses
        cache_hit_rate = (
            self.cache_hits / total_cache if total_cache > 0 else 0.0
        )

        return MetricsData(
            uptime_seconds=get_uptime_seconds(),
            total_requests=self.total_requests,
            errors_last_hour=self.total_errors,  # Simplified
            cache_hit_rate=cache_hit_rate,
            rate_limits_triggered=self.rate_limit_hits,
        )


# Global metrics collector - initialized before use
metrics = MetricsCollector()


async def get_recommendation_metrics(timeframe_hours: int = 24) -> RecommendationMetrics:
    """Compute recommendation quality metrics from interaction logs."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, timeframe_hours))

    async with db_session.SessionLocal() as session:
        try:
            impressions_result = await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM feed_feature_log f
                    WHERE f.created_at >= :cutoff
                    """
                ),
                {"cutoff": cutoff},
            )
            impressions = int(impressions_result.scalar_one() or 0)

            viewed_result = await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM feed_feature_log f
                    WHERE f.created_at >= :cutoff
                      AND EXISTS (
                          SELECT 1
                          FROM interactions i
                          WHERE i.user_id = f.user_id
                            AND i.ai_news_id = f.ai_news_id
                            AND i.created_at >= f.created_at
                            AND COALESCE(i.viewed, FALSE) = TRUE
                      )
                    """
                ),
                {"cutoff": cutoff},
            )
            viewed_clicks = int(viewed_result.scalar_one() or 0)

            time_spent_result = await session.execute(
                text(
                    """
                    SELECT AVG(COALESCE(i.watch_time, 0))
                    FROM interactions i
                    WHERE i.created_at >= :cutoff
                      AND i.watch_time IS NOT NULL
                      AND i.watch_time > 0
                    """
                ),
                {"cutoff": cutoff},
            )
            avg_time_spent = float(time_spent_result.scalar_one() or 0.0)

            positive_result = await session.execute(
                text(
                    """
                    SELECT COUNT(*)
                    FROM feed_feature_log f
                    WHERE f.created_at >= :cutoff
                      AND (
                          EXISTS (
                              SELECT 1
                              FROM interactions i
                              WHERE i.user_id = f.user_id
                                AND i.ai_news_id = f.ai_news_id
                                AND i.created_at >= f.created_at
                                AND COALESCE(i.liked, FALSE) = TRUE
                          )
                          OR EXISTS (
                              SELECT 1
                              FROM saved_news s
                              WHERE s.user_id = f.user_id
                                AND s.ai_news_id = f.ai_news_id
                                AND s.created_at >= f.created_at
                          )
                      )
                    """
                ),
                {"cutoff": cutoff},
            )
            positive_engagements = int(positive_result.scalar_one() or 0)
        except Exception:
            # Some environments may not have social/log tables yet.
            impressions = 0
            viewed_clicks = 0
            avg_time_spent = 0.0
            positive_engagements = 0

    ctr = (viewed_clicks / impressions) if impressions > 0 else 0.0
    recommendation_accuracy = (positive_engagements / impressions) if impressions > 0 else 0.0

    return RecommendationMetrics(
        timeframe_hours=timeframe_hours,
        impressions=impressions,
        viewed_clicks=viewed_clicks,
        ctr=round(ctr, 4),
        avg_time_spent_seconds=round(avg_time_spent, 2),
        positive_engagements=positive_engagements,
        recommendation_accuracy=round(recommendation_accuracy, 4),
    )


async def get_pipeline_metrics(timeframe_hours: int = 24) -> PipelineMetrics:
    """Compute pipeline operational metrics from raw_news and ai_news."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, timeframe_hours))

    async with db_session.SessionLocal() as session:
        total_result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM raw_news
                WHERE created_at >= :cutoff
                """
            ),
            {"cutoff": cutoff},
        )
        total_raw_news = int(total_result.scalar_one() or 0)

        completed_result = await session.execute(
            text(
                """
                                SELECT COUNT(*)
                                FROM raw_news
                                WHERE created_at >= :cutoff
                                    AND process_status IN ('generated', 'completed')
                """
            ),
            {"cutoff": cutoff},
        )
        completed_jobs = int(completed_result.scalar_one() or 0)

        failed_result = await session.execute(
            text(
                """
                SELECT COUNT(*)
                FROM raw_news
                WHERE created_at >= :cutoff
                  AND process_status = 'failed'
                """
            ),
            {"cutoff": cutoff},
        )
        failed_jobs = int(failed_result.scalar_one() or 0)

        pending_result = await session.execute(
            text(
                """
                                SELECT COUNT(*)
                                FROM raw_news
                                WHERE created_at >= :cutoff
                                    AND process_status IN ('pending', 'classified', 'processing')
                """
            ),
            {"cutoff": cutoff},
        )
        pending_jobs = int(pending_result.scalar_one() or 0)

        retry_result = await session.execute(
            text(
                """
                SELECT COALESCE(SUM(CASE WHEN attempt_count > 1 THEN attempt_count - 1 ELSE 0 END), 0),
                       COALESCE(AVG(COALESCE(attempt_count, 0)), 0)
                FROM raw_news
                WHERE created_at >= :cutoff
                """
            ),
            {"cutoff": cutoff},
        )
        retry_row = retry_result.first()
        retry_count = int(retry_row[0] or 0) if retry_row else 0
        avg_attempt_count = float(retry_row[1] or 0.0) if retry_row else 0.0

        latency_rows_result = await session.execute(
            text(
                """
                  SELECT rn.id,
                      rn.created_at AS raw_created_at,
                      MIN(an.created_at) AS first_ai_created_at
                  FROM raw_news rn
                  LEFT JOIN ai_news an ON an.raw_news_id = rn.id
                  WHERE rn.created_at >= :cutoff
                    AND rn.process_status IN ('generated', 'completed')
                GROUP BY rn.id, rn.created_at
                """
            ),
            {"cutoff": cutoff},
        )
        latencies: list[float] = []
        for row in latency_rows_result.mappings().all():
            raw_created_at = row.get("raw_created_at")
            first_ai_created_at = row.get("first_ai_created_at")
            if not raw_created_at or not first_ai_created_at:
                continue
            latency_seconds = (first_ai_created_at - raw_created_at).total_seconds()
            if latency_seconds >= 0:
                latencies.append(latency_seconds)

    avg_latency = (sum(latencies) / len(latencies)) if latencies else 0.0

    return PipelineMetrics(
        timeframe_hours=timeframe_hours,
        total_raw_news=total_raw_news,
        completed_jobs=completed_jobs,
        failed_jobs=failed_jobs,
        pending_jobs=pending_jobs,
        retry_count=retry_count,
        avg_attempt_count=round(avg_attempt_count, 2),
        avg_processing_latency_seconds=round(avg_latency, 2),
    )


async def get_extended_metrics(timeframe_hours: int = 24) -> ExtendedMetricsData:
    """Get API, recommendation, and pipeline metrics as one payload."""
    base_metrics = metrics.get_metrics()
    recommendation, pipeline = await asyncio.gather(
        get_recommendation_metrics(timeframe_hours=timeframe_hours),
        get_pipeline_metrics(timeframe_hours=timeframe_hours),
    )

    return ExtendedMetricsData(
        **base_metrics.model_dump(),
        recommendation=recommendation,
        pipeline=pipeline,
    )
