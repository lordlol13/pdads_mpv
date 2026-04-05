from celery import Celery
from app.backend.core.config import settings

celery_app = Celery(
    "news_brain",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["brain.tasks.pipeline_tasks"],
)

celery_app.conf.timezone = "Asia/Tashkent"
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