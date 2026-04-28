"""Celery app entrypoint module.

Allows worker startup with:
    celery -A news_brain worker --loglevel=info
"""

from app.backend.core.celery_app import celery_app as app

__all__ = ["app"]

