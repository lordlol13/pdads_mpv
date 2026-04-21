from __future__ import annotations
from typing import Any
import logging

from app.backend.core.celery_app import celery_app

LOG = logging.getLogger("parser_task")


@celery_app.task(
    name="app.backend.tasks.parser_task.parse_news_task",
    autoretry_for=(ConnectionError, TimeoutError, Exception),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=2,
)
def parse_news_task() -> dict[str, Any]:
    """Celery task entrypoint that runs the parser and returns a summary."""
    LOG.info("parse_news_task started")
    try:
        # import at runtime to keep Celery worker startup resilient
        from app.backend.services.parser import run_parser

        result = run_parser(per_rss_limit=5, per_site_limit=10)
        LOG.info("parse_news_task finished: %s", result)
        return {"status": "ok", "detail": result}
    except Exception as e:
        LOG.exception("parse_news_task failed: %s", e)
        raise
