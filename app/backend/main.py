"""
FastAPI application entry point with middleware, error handlers, and routing.

Provides REST API for:
- Authentication & authorization
- News feed personalization
- LLM-powered content generation
- Admin pipeline control
- System health monitoring
"""

from pathlib import Path
from logging import getLogger
import time

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse
import uuid

from app.backend.api.routes.auth import router as auth_router
from app.backend.api.routes.feed import router as feed_router
from app.backend.api.routes.health import router as health_router
from app.backend.api.routes.ingestion import router as ingestion_router
from app.backend.api.routes.pipeline import router as pipeline_router
from app.backend.core.config import settings
from app.backend.core.errors import (
    AppException,
    to_http_exception,
    error_response,
    ErrorCode,
)
from app.backend.core.health import metrics, get_system_health
from app.backend.core.logging import ContextLogger

# Initialize structured logger
logger = ContextLogger(__name__)

# =====================================================================
# Application Factory
# =====================================================================

app = FastAPI(
    title="PA.ADS MVP - AI News Feed",
    description="Personalized news feed powered by embeddings and AI-driven content generation",
    version="0.1.0",
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
)

# =====================================================================
# Middleware Stack
# =====================================================================

# Add request correlation ID
@app.middleware("http")
async def add_correlation_id_and_logging(request: Request, call_next):
    """
    Add correlation ID to all requests and set up request/response logging.
    
    Propagates correlation ID through:
    - request.state for local access
    - X-Correlation-ID header in response
    - Logger context for all downstream logs
    """
    correlation_id = request.headers.get("X-Correlation-ID") or str(uuid.uuid4())
    request.state.correlation_id = correlation_id
    
    # Set correlation ID in logger context
    logger.set_correlation_id(correlation_id)
    logger.set_context(
        method=request.method,
        path=request.url.path,
        client_host=request.client.host if request.client else None,
    )
    
    start_time = time.time()
    
    try:
        response = await call_next(request)
    except Exception as exc:
        # Log unhandled exceptions before they're caught by exception handlers
        duration = (time.time() - start_time) * 1000  # ms
        logger.error(
            f"Request failed with exception",
            duration_ms=duration,
            status=500,
            exception_type=exc.__class__.__name__,
        )
        raise
    
    # Calculate response time
    duration_ms = (time.time() - start_time) * 1000
    
    # Log request/response
    if response.status_code >= 500:
        log_level = "error"
        logger.error(
            f"{request.method} {request.url.path}",
            status=response.status_code,
            duration_ms=f"{duration_ms:.2f}",
        )
    elif response.status_code >= 400:
        logger.warning(
            f"{request.method} {request.url.path}",
            status=response.status_code,
            duration_ms=f"{duration_ms:.2f}",
        )
    else:
        logger.info(
            f"{request.method} {request.url.path} - {response.status_code}",
            duration_ms=f"{duration_ms:.2f}",
        )
    
    response.headers["X-Correlation-ID"] = correlation_id
    response.headers["X-Response-Time"] = f"{duration_ms:.2f}ms"
    return response



# CORS configuration
cors_origins = settings.cors_allow_origins
allow_credentials = "*" not in cors_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_origin_regex=settings.CORS_ALLOW_ORIGIN_REGEX or None,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*", "X-Correlation-ID"],
    max_age=86400,  # 1 day
)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SESSION_SECRET_KEY,
    same_site="lax",
    https_only=not settings.DEBUG,
)

# Trusted hosts (security)
if not settings.DEBUG:
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=settings.trusted_hosts,
    )

# =====================================================================
# Exception Handlers
# =====================================================================

@app.exception_handler(AppException)
async def app_exception_handler(request: Request, exc: AppException):
    """Handle application-specific exceptions with proper error codes."""
    correlation_id = getattr(request.state, "correlation_id", None)
    logger.set_correlation_id(correlation_id)
    
    detail = error_response(
        code=exc.code,
        message=exc.message,
        field=exc.field,
        details=exc.details,
        correlation_id=correlation_id,
    )
    
    logger.warning(
        f"Application exception: {exc.code.value}",
        code=exc.code.value,
        message=exc.message,
        field=exc.field,
        status=exc.status_code,
    )
    
    return JSONResponse(status_code=exc.status_code, content=detail)


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle unexpected exceptions with sanitized error response."""
    correlation_id = getattr(request.state, "correlation_id", None)
    logger.set_correlation_id(correlation_id)
    
    logger.exception(
        "Unhandled exception",
        exception_type=exc.__class__.__name__,
    )
    
    # Don't expose internal error details in production
    if settings.DEBUG:
        message = str(exc)
        details = {"exception": exc.__class__.__name__}
    else:
        message = "Internal server error. Please try again later."
        details = None
    
    detail = error_response(
        code=ErrorCode.INTERNAL_ERROR,
        message=message,
        details=details,
        correlation_id=correlation_id,
    )
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content=detail,
    )

# =====================================================================
# Request Metrics Tracking
# =====================================================================

@app.middleware("http")
async def track_metrics(request: Request, call_next):
    """Track request metrics for monitoring."""
    response = await call_next(request)
    
    is_error = response.status_code >= 400
    metrics.record_request(is_error=is_error)
    
    return response

# =====================================================================
# Routers
# =====================================================================

# Health & monitoring endpoints (highest priority)
app.include_router(health_router, prefix="/api")

# Compatibility endpoints for platforms expecting root-level health checks
@app.get("/health")
def root_liveness():
    """Compatibility liveness endpoint (keeps orchestration probes happy)."""
    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "alive"})


@app.get("/ready")
async def root_readiness():
    """Compatibility readiness endpoint that mirrors `/api/health/ready`."""
    health = await get_system_health()
    if health.status == "unhealthy":
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={"status": "unhealthy", "components": [c.dict() for c in health.components]},
        )
    return JSONResponse(status_code=status.HTTP_200_OK, content={"status": "ready", "components": len(health.components)})

# API routes
app.include_router(auth_router, prefix="/api")
app.include_router(auth_router)  # Also register auth router at root for compatibility with clients calling /auth/*
app.include_router(ingestion_router, prefix="/api")
app.include_router(feed_router, prefix="/api")
app.include_router(pipeline_router, prefix="/api")

# =====================================================================
# Static Files (Frontend)
# =====================================================================

_frontend_dist = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
else:
    logger.warning(f"Frontend dist directory not found: {_frontend_dist}")

# =====================================================================
# Startup/Shutdown Events
# =====================================================================

@app.on_event("startup")
async def startup():
    """Application startup hook."""
    logger.info(
        f"Starting {settings.APP_NAME}",
        extra={
            "environment": settings.APP_ENV,
            "debug": settings.DEBUG,
        },
    )


@app.on_event("shutdown")
async def shutdown():
    """Application shutdown hook."""
    from app.backend.services.resilience_service import shutdown_resilience
    
    await shutdown_resilience()
    logger.info("Application shutdown complete")
