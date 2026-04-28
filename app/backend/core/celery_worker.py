"""
Celery worker/beat entry point.

Import ONLY what is needed for Celery — do NOT import app.backend.main
or anything that triggers FastAPI application creation.

Usage:
  worker: celery -A app.backend.core.celery_worker:celery_app worker --loglevel=info --pool=solo
  beat:   celery -A app.backend.core.celery_worker:celery_app beat   --loglevel=info
"""

from app.backend.core.celery_app import celery_app  # noqa: F401  re-exported for -A flag
