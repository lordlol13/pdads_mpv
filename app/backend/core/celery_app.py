from celery import Celery
import os
import logging
from typing import Any

import redis as redis_lib

from app.backend.core.config import settings

logger = logging.getLogger(__name__)


celery_app = Celery(
    "news_brain",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

# FIX START - Set beat_schedule immediately after app creation (before autodiscover)
celery_app.conf.update(
    beat_schedule={
        "parse-news": {
            "task": "app.backend.tasks.parser_task.parse_news_task",
            "schedule": 300.0,
        },
        "process-news": {
            "task": "brain.tasks.pipeline_tasks.process_all_task",
            "schedule": 600.0,
        },
    },
    timezone="UTC",
)
print("[BEAT DEBUG] schedule keys:", list(celery_app.conf.beat_schedule.keys()))
# FIX END

# Корректная регистрация задач
celery_app.autodiscover_tasks(
    [
        "app.backend.tasks",
        "brain.tasks",
        "recommender",
    ],
    force=True,
)

try:
    import app.backend.tasks.parser_task  # noqa: F401
    import brain.tasks.pipeline_tasks  # noqa: F401
    import recommender.tasks  # noqa: F401
except Exception as import_exc:
    logger.exception("[CELERY] explicit task import failed: %s", import_exc)


# Log configuration
# FIX: Only enable eager mode when explicitly requested (not by default in dev)
# Eager mode causes event loop conflicts with asyncio.run()
is_eager = os.getenv("CELERY_TASK_ALWAYS_EAGER", "").lower() == "true"
logger.info("[CELERY] Starting with APP_ENV=%s, task_always_eager=%s, broker=%s", 
            settings.APP_ENV, is_eager, settings.CELERY_BROKER_URL)

# Basic runtime tuning for workers (can be overridden via env vars)
celery_app.conf.update(
    timezone="Asia/Tashkent",
    worker_prefetch_multiplier=int(os.getenv("CELERY_PREFETCH_MULTIPLIER", str(settings.CELERY_PREFETCH_MULTIPLIER))),
    worker_max_tasks_per_child=int(os.getenv("CELERY_MAX_TASKS_PER_CHILD", str(settings.CELERY_MAX_TASKS_PER_CHILD))),
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # FIX: Disabled eager mode by default to avoid event loop conflicts
    # Only enable with CELERY_TASK_ALWAYS_EAGER=true
    task_always_eager=is_eager,
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", str(settings.CELERY_TASK_TIME_LIMIT))),
    worker_concurrency=int(os.getenv("CELERY_WORKER_CONCURRENCY", str(settings.CELERY_WORKER_CONCURRENCY))),
    broker_transport_options={"visibility_timeout": int(os.getenv("CELERY_BROKER_VISIBILITY_TIMEOUT", "3600"))},
)

# Worker startup logging
print(f"[WORKER] Celery starting")
print(f"[WORKER] Broker: {settings.CELERY_BROKER_URL[:40]}..." if settings.CELERY_BROKER_URL else "[WORKER] Broker: NOT SET")
print(f"[WORKER] Backend: {settings.CELERY_RESULT_BACKEND[:40]}..." if settings.CELERY_RESULT_BACKEND else "[WORKER] Backend: NOT SET")
print(f"[WORKER] Eager mode: {is_eager}")

# FIX START - Configure beat scheduler to use /tmp for Railway (avoid cached schedule issues)
celery_app.conf.beat_scheduler = "celery.beat:PersistentScheduler"
celery_app.conf.beat_schedule_filename = "/tmp/celerybeat-schedule"
print("[BEAT] schedule file set to /tmp/celerybeat-schedule")
# FIX END

try:
    print("[CELERY] registered tasks:", sorted(celery_app.tasks.keys()))
except Exception as tasks_exc:
    logger.exception("[CELERY] failed to print registered tasks: %s", tasks_exc)


def is_redis_available() -> bool:
    """Check if Redis broker is available for task queuing."""
    import os
    # Skip if explicitly disabled
    if os.getenv("SKIP_CELERY_TASKS", "").lower() == "true":
        return False
    # Check if broker is configured
    broker = (settings.CELERY_BROKER_URL or "").strip()
    if not broker:
        return False
    # Production Redis should not be localhost
    if broker.startswith("redis://localhost") or broker.startswith("redis://127.0.0.1"):
        # Local Redis - skip in production
        return False
    return True


# FIX START - Redis client for rate limiting
_redis_client = None

def _get_redis_client():
    global _redis_client
    if _redis_client is None and is_redis_available():
        try:
            _redis_client = redis_lib.from_url(settings.REDIS_URL, decode_responses=True)
        except Exception as e:
            logger.warning("[CELERY] Failed to connect to Redis for rate limiting: %s", e)
    return _redis_client


def send_task_safe(name: str, args: tuple | None = None, kwargs: dict | None = None, **options) -> Any:
    """Send a Celery task only if Redis is available, otherwise log and skip.
    
    Rate limiting: Max 1 task per user per 60 seconds for recommender.refresh_user_embedding.
    """
    if not is_redis_available():
        logger.debug("[CELERY] Skipping task %s (Redis not available)", name)
        return None
    
    # FIX START - Rate limiting for recommender task
    if name == "recommender.refresh_user_embedding" and args:
        user_id = args[0] if args and len(args) > 0 else None
        if user_id:
            redis_client = _get_redis_client()
            if redis_client:
                key = f"rate_limit:embedding:{user_id}"
                # SET key with 60s expiry (NX = only if not exists)
                # Returns True if key was set, False if already exists
                if not redis_client.set(key, "1", ex=60, nx=True):
                    logger.debug("[CELERY] Rate limited task %s for user_id=%s", name, user_id)
                    return None
    # FIX END
    
    try:
        return celery_app.send_task(name, args=args, kwargs=kwargs, **options)
    except Exception as e:
        logger.warning("[CELERY] Failed to send task %s: %s", name, e)
        return None
