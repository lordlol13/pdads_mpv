"""Celery task bindings for recommender namespace.

This module ensures Celery can import `recommender.tasks` and register
`recommender.refresh_user_embedding`.
"""

from brain.tasks.pipeline_tasks import refresh_user_embedding_task

__all__ = ["refresh_user_embedding_task"]

