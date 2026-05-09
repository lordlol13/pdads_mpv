"""Celery task bindings for recommender namespace.

This module ensures Celery can import `recommender.tasks` for autodiscovery.
The actual task `recommender.refresh_user_embedding` is registered in brain.tasks.pipeline_tasks.
"""

# NOTE: Deliberately empty to avoid circular imports with pipeline_tasks.py
# The task is registered via Celery decorator in brain.tasks.pipeline_tasks.py

