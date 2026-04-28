from celery import Celery
import os
import logging
from app.backend.core.config import settings

logger = logging.getLogger(__name__)


celery_app = Celery(
    "news_brain",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
)

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
is_eager = False  # Принудительно отключаем eager-режим для production
if (os.getenv("CELERY_TASK_ALWAYS_EAGER", "").lower() == "true") or (str(settings.APP_ENV).lower() == "dev"):
    is_eager = True
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
        # For local development allow running tasks eagerly when Redis is not available.
        # Enable with CELERY_TASK_ALWAYS_EAGER=true or when APP_ENV=dev.
        task_always_eager=is_eager,
    task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", str(settings.CELERY_TASK_TIME_LIMIT))),
    worker_concurrency=int(os.getenv("CELERY_WORKER_CONCURRENCY", str(settings.CELERY_WORKER_CONCURRENCY))),
    broker_transport_options={"visibility_timeout": int(os.getenv("CELERY_BROKER_VISIBILITY_TIMEOUT", "3600"))},
)

celery_app.conf.beat_schedule = {
    "parse-news": {
        "task": "app.backend.tasks.parser_task.parse_news_task",
        "schedule": 300.0,
    },
    "process-news": {
        "task": "brain.tasks.pipeline_tasks.process_all_task",
        "schedule": 600.0,
    },
}

try:
    print("[CELERY] registered tasks:", sorted(celery_app.tasks.keys()))
except Exception as tasks_exc:
    logger.exception("[CELERY] failed to print registered tasks: %s", tasks_exc)
