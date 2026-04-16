from celery import Celery
import os
from app.backend.core.config import settings


celery_app = Celery(
    "news_brain",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["brain.tasks.pipeline_tasks"],
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
        task_always_eager=(os.getenv("CELERY_TASK_ALWAYS_EAGER", "").lower() == "true") or (str(settings.APP_ENV).lower() == "dev"),
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", str(settings.CELERY_TASK_TIME_LIMIT))),
    worker_concurrency=int(os.getenv("CELERY_WORKER_CONCURRENCY", str(settings.CELERY_WORKER_CONCURRENCY))),
    broker_transport_options={"visibility_timeout": int(os.getenv("CELERY_BROKER_VISIBILITY_TIMEOUT", "3600"))},
)

celery_app.conf.beat_schedule = {
    "scheduled-ingestion-every-15-minutes": {
        "task": "brain.scheduled_ingestion",
        "schedule": settings.SCHEDULER_INTERVAL_MINUTES * 60,
    },
    "scheduled-cleanup-ai-products": {
        "task": "brain.scheduled_cleanup_ai_products",
        "schedule": settings.SCHEDULER_CLEANUP_INTERVAL_HOURS * 60 * 60,
    }
}