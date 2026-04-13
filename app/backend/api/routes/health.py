"""
Health check and monitoring endpoints.

Provides information about system health, component status, and metrics.
"""

from fastapi import APIRouter, Depends, status
from logging import getLogger

from app.backend.core.health import (
    get_system_health,
    SystemHealth,
    MetricsData,
    ExtendedMetricsData,
    RecommendationMetrics,
    PipelineMetrics,
    get_extended_metrics,
    get_recommendation_metrics,
    get_pipeline_metrics,
    metrics,
)
from app.backend.core.errors import (
    success_response,
    error_response,
    ErrorCode,
)

logger = getLogger(__name__)
router = APIRouter(tags=["monitoring"], prefix="/health")


@router.get(
    "/live",
    status_code=status.HTTP_200_OK,
    summary="Liveness probe",
    description="Simple health check for Kubernetes/orchestrators. Returns immediately.",
)
def liveness_probe():
    """Liveness probe - application is running."""
    return success_response({"status": "alive"})


@router.get(
    "/ready",
    status_code=status.HTTP_200_OK,
    summary="Readiness probe",
    description="Checks if service is ready to accept traffic.",
)
async def readiness_probe():
    """Readiness probe - service is ready to handle requests."""
    health = await get_system_health()
    
    if health.status == "unhealthy":
        return error_response(
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message="Service is not ready - critical components unhealthy",
            details={"components": [c.dict() for c in health.components]},
        )
    
    return success_response({"status": "ready", "components": len(health.components)})


@router.get(
    "/system",
    response_model=SystemHealth,
    status_code=status.HTTP_200_OK,
    summary="System health status",
    description="Detailed health status of all system components.",
)
async def system_health():
    """
    Get detailed system health status.
    
    Checks:
    - Database connectivity
    - Redis connectivity
    - External APIs (News API, LLM services)
    - Celery task queue
    
    Returns component health with response times and details.
    """
    return await get_system_health()


@router.get(
    "/metrics",
    response_model=ExtendedMetricsData,
    status_code=status.HTTP_200_OK,
    summary="Application metrics",
    description="Combined API, recommendation, and pipeline metrics.",
)
async def application_metrics():
    """
    Get application metrics snapshot.
    
    Metrics include:
    - API runtime metrics (requests, errors, cache rate)
    - Recommendation metrics (CTR, time spent, recommendation accuracy)
    - Pipeline metrics (failed tasks, latency, retry count)
    """
    return await get_extended_metrics(timeframe_hours=24)


@router.get(
    "/metrics/recommendations",
    response_model=RecommendationMetrics,
    status_code=status.HTTP_200_OK,
    summary="Recommendation metrics",
    description="CTR, time spent, and recommendation accuracy over the last 24h.",
)
async def recommendation_metrics():
    """Get recommendation quality metrics."""
    return await get_recommendation_metrics(timeframe_hours=24)


@router.get(
    "/metrics/pipeline",
    response_model=PipelineMetrics,
    status_code=status.HTTP_200_OK,
    summary="Pipeline monitoring metrics",
    description="Failed tasks, latency, retry count and queue status over the last 24h.",
)
async def pipeline_metrics():
    """Get pipeline reliability and latency metrics."""
    return await get_pipeline_metrics(timeframe_hours=24)
