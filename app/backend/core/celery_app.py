from celery import Celery
import os
import logging
from app.backend.core.config import settings

logger = logging.getLogger(__name__)

# Task modules that must be imported by every Celery process (worker, beat, app).
# Listed here so the include= argument and autodiscover_tasks() both reference
# the same canonical list.
CELERY_TASK_MODULES = [
    "brain.tasks.pipeline_tasks",
    "app.backend.tasks.parser_task",
]

celery_app = Celery(
    "news_brain",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=CELERY_TASK_MODULES,
)

# Eagerness: only enable in dev when Redis is unavailable.
# In production (APP_ENV != "dev") this MUST be False so tasks are sent to the
# broker and executed by the worker — not run inline by the caller.
_app_env = str(settings.APP_ENV).strip().lower()
_eager_env_flag = os.getenv("CELERY_TASK_ALWAYS_EAGER", "").strip().lower() == "true"
_is_eager = _eager_env_flag or (_app_env == "dev")

logger.info(
    "[CELERY] Configuring: APP_ENV=%s, task_always_eager=%s, broker=%s",
    settings.APP_ENV,
    _is_eager,
    settings.CELERY_BROKER_URL,
)

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
    # For local development allow running tasks eagerly when Redis is not available.
    # Enable with CELERY_TASK_ALWAYS_EAGER=true or when APP_ENV=dev.
    # WARNING: must be False in production or tasks will never reach the worker.
    task_always_eager=_is_eager,
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", str(settings.CELERY_TASK_TIME_LIMIT))),
    worker_concurrency=int(os.getenv("CELERY_WORKER_CONCURRENCY", str(settings.CELERY_WORKER_CONCURRENCY))),
    broker_transport_options={"visibility_timeout": int(os.getenv("CELERY_BROKER_VISIBILITY_TIMEOUT", "3600"))},
)

# ---------------------------------------------------------------------------
# Beat schedule
# Task names MUST match the name= argument in the @celery_app.task decorator.
# ---------------------------------------------------------------------------
celery_app.conf.beat_schedule = {
    "scheduled-ingestion-every-15-minutes": {
        "task": "brain.scheduled_ingestion",
        "schedule": settings.SCHEDULER_INTERVAL_MINUTES * 60,
    },
    "scheduled-cleanup-ai-products": {
        "task": "brain.scheduled_cleanup_ai_products",
        "schedule": settings.SCHEDULER_CLEANUP_INTERVAL_HOURS * 60 * 60,
    },
    "scheduled-feed-ingestion-every-15-minutes": {
        "task": "brain.scheduled_feed_ingestion",
        "schedule": settings.SCHEDULER_INTERVAL_MINUTES * 60,
    },
    "parse-news": {
        "task": "app.backend.tasks.parser_task.parse_news_task",
        "schedule": 15 * 60,
    },
}

# ---------------------------------------------------------------------------
# Explicit task discovery — ensures all task modules are imported and their
# @celery_app.task decorators are executed regardless of which process starts
# first (worker, beat, or web).  The include= list above handles the same
# thing for worker/beat processes; this call makes it explicit and logs the
# result so registration problems are visible in startup logs.
# ---------------------------------------------------------------------------
celery_app.autodiscover_tasks(CELERY_TASK_MODULES, force=True)

# Log registered tasks so misconfiguration is immediately visible in logs.
try:
    registered = sorted(celery_app.tasks.keys())
    logger.info("[CELERY] Registered tasks (%d): %s", len(registered), registered)
except Exception:
    pass