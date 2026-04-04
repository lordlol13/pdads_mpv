from celery import Celery
from app.backend.core.config import settings

celery_app = Celery(
    "news_brain",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=["brain.tasks.pipeline_tasks"],
)