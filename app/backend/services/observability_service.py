"""
Observability Service — Production monitoring and metrics for the news pipeline.

This module provides:
- Structured logging with correlation IDs (JSON for ELK/Loki)
- Metrics collection (counters, timers, gauges)
- Pipeline health monitoring with alerting thresholds
- Prometheus exposition format for external monitoring
- K8s readiness/liveness probes
- Request tracing

EXTERNAL INTEGRATIONS:
- Prometheus: GET /api/pipeline/metrics/prometheus
- Grafana: Use Prometheus as data source
- K8s probes: /api/pipeline/ready (readiness), /api/pipeline/live (liveness)
- DataDog/New Relic: Use Prometheus endpoint or JSON logs

PRODUCTION SETUP:
1. Prometheus scraping: Add job for /api/pipeline/metrics/prometheus
2. K8s probes: Configure readiness at /api/pipeline/ready, liveness at /api/pipeline/live
3. Log aggregation: Configure fluent-bit/filebeat to collect logs from logs/app.log (JSON format)
4. Alerting: Set up alerts on pipeline_failed_total or pipeline_runs_total (stalled)
"""

import json
import logging
import time  # FIX - Required for timing operations
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from collections import defaultdict
import asyncio

# Context variable for correlation IDs
correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")


@dataclass
class PipelineMetrics:
    """Real-time pipeline metrics."""
    raw_news_fetched: int = 0
    ai_news_created: int = 0
    processed: int = 0
    failed: int = 0
    skipped: int = 0
    avg_latency_ms: float = 0.0
    last_run: Optional[str] = None
    errors: list[str] = field(default_factory=list)


class MetricsCollector:
    """In-memory metrics collector with automatic aggregation."""

    def __init__(self):
        self.counters: dict[str, int] = defaultdict(int)
        self.timers: dict[str, list[float]] = defaultdict(list)
        self.gauges: dict[str, float] = {}
        self.start_times: dict[str, float] = {}
        self._lock = asyncio.Lock()

    async def increment(self, name: str, value: int = 1):
        """Increment a counter metric."""
        async with self._lock:
            self.counters[name] += value

    async def gauge(self, name: str, value: float):
        """Set a gauge metric."""
        async with self._lock:
            self.gauges[name] = value

    def timer_start(self, name: str):
        """Start a timer."""
        self.start_times[name] = time.time()

    async def timer_end(self, name: str):
        """End a timer and record duration."""
        if name not in self.start_times:
            return
        duration = (time.time() - self.start_times[name]) * 1000  # ms
        async with self._lock:
            self.timers[name].append(duration)
            # Keep only last 100 measurements
            if len(self.timers[name]) > 100:
                self.timers[name] = self.timers[name][-100:]
        return duration

    async def get_stats(self) -> dict[str, Any]:
        """Get current metrics snapshot."""
        async with self._lock:
            stats = {
                "counters": dict(self.counters),
                "gauges": dict(self.gauges),
                "timers": {
                    name: {
                        "count": len(times),
                        "avg": sum(times) / len(times) if times else 0,
                        "min": min(times) if times else 0,
                        "max": max(times) if times else 0,
                    }
                    for name, times in self.timers.items()
                },
                "timestamp": datetime.utcnow().isoformat(),
            }
        return stats

    async def reset(self):
        """Reset all metrics."""
        async with self._lock:
            self.counters.clear()
            self.timers.clear()
            self.gauges.clear()
            self.start_times.clear()


# Global metrics collector
metrics = MetricsCollector()


class StructuredLogger:
    """Structured logger with JSON output and correlation IDs."""

    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.name = name

    def _log(self, level: str, message: str, **kwargs):
        """Create structured log entry."""
        entry = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": level,
            "logger": self.name,
            "message": message,
            "correlation_id": correlation_id.get(""),
            **kwargs,
        }
        # Log as JSON for structured parsing
        self.logger.log(
            getattr(logging, level.upper()),
            json.dumps(entry, ensure_ascii=False, default=str),
        )
        return entry

    def info(self, message: str, **kwargs):
        return self._log("info", message, **kwargs)

    def warning(self, message: str, **kwargs):
        return self._log("warning", message, **kwargs)

    def error(self, message: str, **kwargs):
        return self._log("error", message, **kwargs)

    def debug(self, message: str, **kwargs):
        return self._log("debug", message, **kwargs)

    def metric(self, metric_name: str, value: float, unit: str = "count", **tags):
        """Log a metric point."""
        return self._log(
            "info",
            f"METRIC: {metric_name}",
            metric_name=metric_name,
            metric_value=value,
            metric_unit=unit,
            tags=tags,
        )


def get_logger(name: str) -> StructuredLogger:
    """Get a structured logger instance."""
    return StructuredLogger(name)


def set_correlation_id(cid: str):
    """Set correlation ID for current context."""
    correlation_id.set(cid)


def get_correlation_id() -> str:
    """Get current correlation ID."""
    return correlation_id.get("")


class PipelineHealthMonitor:
    """Monitor pipeline health and trigger alerts."""

    # Alert thresholds
    THRESHOLDS = {
        "failure_rate": 0.3,  # 30% failure rate triggers alert
        "latency_ms": 30000,  # 30s latency triggers alert
        "stalled_minutes": 10,  # No activity for 10 min triggers alert
    }

    def __init__(self):
        self.pipeline_metrics = PipelineMetrics()
        self.last_activity = datetime.utcnow()
        self.alerts: list[dict] = []
        self.logger = get_logger("pipeline.health")

    def update_activity(self):
        """Record pipeline activity."""
        self.last_activity = datetime.utcnow()

    async def check_health(self) -> dict[str, Any]:
        """Run health checks and return status."""
        now = datetime.utcnow()
        stalled_seconds = (now - self.last_activity).total_seconds()

        # Calculate failure rate
        total = self.pipeline_metrics.processed + self.pipeline_metrics.failed
        failure_rate = (
            self.pipeline_metrics.failed / total if total > 0 else 0
        )

        health = {
            "status": "healthy",
            "checks": {
                "failure_rate": {
                    "value": round(failure_rate, 2),
                    "threshold": self.THRESHOLDS["failure_rate"],
                    "passed": failure_rate < self.THRESHOLDS["failure_rate"],
                },
                "stalled": {
                    "seconds_since_activity": int(stalled_seconds),
                    "threshold_seconds": self.THRESHOLDS["stalled_minutes"] * 60,
                    "passed": stalled_seconds < self.THRESHOLDS["stalled_minutes"] * 60,
                },
            },
            "metrics": {
                "raw_news_fetched": self.pipeline_metrics.raw_news_fetched,
                "ai_news_created": self.pipeline_metrics.ai_news_created,
                "processed": self.pipeline_metrics.processed,
                "failed": self.pipeline_metrics.failed,
                "skipped": self.pipeline_metrics.skipped,
            },
            "timestamp": now.isoformat(),
        }

        # Determine overall status
        if not all(c["passed"] for c in health["checks"].values()):
            health["status"] = "degraded" if any(
                c["passed"] for c in health["checks"].values()
            ) else "unhealthy"

            # Log alert
            failed_checks = [
                name for name, c in health["checks"].items() if not c["passed"]
            ]
            self.logger.error(
                "Pipeline health check failed",
                failed_checks=failed_checks,
                health=health,
            )

        return health

    def record_pipeline_run(
        self,
        fetched: int,
        created: int,
        processed: int,
        failed: int,
        skipped: int,
        latency_ms: float,
    ):
        """Record metrics from a pipeline run."""
        self.pipeline_metrics.raw_news_fetched = fetched
        self.pipeline_metrics.ai_news_created = created
        self.pipeline_metrics.processed = processed
        self.pipeline_metrics.failed = failed
        self.pipeline_metrics.skipped = skipped
        self.pipeline_metrics.avg_latency_ms = latency_ms
        self.pipeline_metrics.last_run = datetime.utcnow().isoformat()
        self.update_activity()

        self.logger.info(
            "Pipeline run completed",
            fetched=fetched,
            created=created,
            processed=processed,
            failed=failed,
            skipped=skipped,
            latency_ms=round(latency_ms, 2),
        )


# Global health monitor
health_monitor = PipelineHealthMonitor()


class Timer:
    """Context manager for timing operations."""

    def __init__(self, name: str, logger: Optional[StructuredLogger] = None):
        self.name = name
        self.logger = logger or get_logger("timer")
        self.start_time: Optional[float] = None
        self.duration_ms: Optional[float] = None

    async def __aenter__(self):
        self.start_time = time.time()
        metrics.timer_start(self.name)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.duration_ms = await metrics.timer_end(self.name)
        status = "error" if exc_type else "success"
        self.logger.metric(
            f"timer.{self.name}",
            self.duration_ms or 0,
            unit="ms",
            status=status,
        )


async def get_system_metrics() -> dict[str, Any]:
    """Get comprehensive system metrics."""
    from sqlalchemy import text
    from app.backend.db.session import SessionLocal

    async with SessionLocal() as session:
        # Database counts
        raw_count = await session.execute(text("SELECT COUNT(*) FROM raw_news"))
        ai_count = await session.execute(text("SELECT COUNT(*) FROM ai_news"))
        user_count = await session.execute(text("SELECT COUNT(*) FROM users"))

        # Pipeline status breakdown
        status_result = await session.execute(
            text("SELECT process_status, COUNT(*) as cnt FROM raw_news GROUP BY process_status")
        )
        status_breakdown = {row[0]: row[1] for row in status_result.fetchall()}

    return {
        "database": {
            "raw_news_count": raw_count.scalar_one(),
            "ai_news_count": ai_count.scalar_one(),
            "users_count": user_count.scalar_one(),
            "raw_news_by_status": status_breakdown,
        },
        "metrics": await metrics.get_stats(),
        "health": await health_monitor.check_health(),
    }


# FIX START - Prometheus exposition format for external monitoring
async def get_prometheus_metrics() -> str:
    """
    Generate Prometheus exposition format metrics.
    Used by Prometheus, Grafana, DataDog, etc.
    """
    lines = []
    stats = await metrics.get_stats()

    # HELP and TYPE lines (Prometheus format)
    lines.append("# HELP pipeline_runs_total Total pipeline runs")
    lines.append("# TYPE pipeline_runs_total counter")
    lines.append(f"pipeline_runs_total {stats['counters'].get('pipeline.runs', 0)}")

    lines.append("# HELP pipeline_processed_total Total items processed")
    lines.append("# TYPE pipeline_processed_total counter")
    lines.append(f"pipeline_processed_total {stats['counters'].get('pipeline.processed', 0)}")

    lines.append("# HELP pipeline_failed_total Total items failed")
    lines.append("# TYPE pipeline_failed_total counter")
    lines.append(f"pipeline_failed_total {stats['counters'].get('pipeline.failed', 0)}")

    lines.append("# HELP pipeline_created_total Total ai_news created")
    lines.append("# TYPE pipeline_created_total counter")
    lines.append(f"pipeline_created_total {stats['counters'].get('pipeline.created', 0)}")

    lines.append("# HELP pipeline_ai_news_gauge Current ai_news count")
    lines.append("# TYPE pipeline_ai_news_gauge gauge")
    lines.append(f"pipeline_ai_news_gauge {stats['gauges'].get('pipeline.ai_news_total', 0)}")

    # Timer metrics
    for name, timer_data in stats['timers'].items():
        metric_name = name.replace('.', '_').replace('-', '_')
        lines.append(f"# HELP {metric_name}_duration_ms {name} duration")
        lines.append(f"# TYPE {metric_name}_duration_ms summary")
        lines.append(f"{metric_name}_duration_ms_count {timer_data['count']}")
        lines.append(f"{metric_name}_duration_ms_sum {timer_data['avg'] * timer_data['count']}")

    return "\n".join(lines)


async def get_simple_health() -> dict[str, Any]:
    """
    Simple health check for load balancers (K8s, ALB, etc.).
    Returns: {'status': 'healthy'|'unhealthy', 'code': 200|503}
    """
    health = await health_monitor.check_health()

    # Simple pass/fail for load balancers
    if health["status"] == "healthy":
        return {"status": "healthy", "code": 200}
    else:
        return {"status": "unhealthy", "code": 503, "failed_checks": [
            name for name, check in health["checks"].items() if not check["passed"]
        ]}


# FIX START - Startup observability logging
async def log_startup_info():
    """
    Log startup information for observability.
    Call this on application startup.
    """
    from app.backend.core.config import settings
    from app.backend.db.session import SessionLocal
    from sqlalchemy import text

    logger = get_logger("startup")

    async with SessionLocal() as session:
        raw_count = await session.execute(text("SELECT COUNT(*) FROM raw_news"))
        ai_count = await session.execute(text("SELECT COUNT(*) FROM ai_news"))
        user_count = await session.execute(text("SELECT COUNT(*) FROM users"))

    logger.info(
        "Application startup",
        version="1.0.0",
        environment="production" if not settings.DEBUG else "development",
        database_url=str(settings.DATABASE_URL).split("@")[-1] if settings.DATABASE_URL else "none",  # Hide credentials
        redis_url=str(settings.REDIS_URL).split("@")[-1] if settings.REDIS_URL else "none",
        ai_news_count=ai_count.scalar_one(),
        raw_news_count=raw_count.scalar_one(),
        users_count=user_count.scalar_one(),
        celery_broker=bool(settings.CELERY_BROKER_URL),
        openai_enabled=bool(settings.OPENAI_API_KEY),
    )

    # Update metrics
    await metrics.gauge("pipeline.ai_news_total", ai_count.scalar_one())
    await metrics.gauge("pipeline.raw_news_total", raw_count.scalar_one())
    await metrics.gauge("pipeline.users_total", user_count.scalar_one())
# FIX END
