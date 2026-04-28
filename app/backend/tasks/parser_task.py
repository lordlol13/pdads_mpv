from __future__ import annotations
from typing import Any
import logging

from app.backend.core.celery_app import celery_app

LOG = logging.getLogger("parser_task")

# Log at import time so worker/beat startup logs confirm this module was loaded.
LOG.info("[PARSER] parser_task module loaded — parse_news_task is being registered")


@celery_app.task(
    name="app.backend.tasks.parser_task.parse_news_task",
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_jitter=True,
    max_retries=2,
)
def parse_news_task(self) -> dict[str, Any]:
    """Celery task entrypoint that runs the parser and returns a summary.

    Scheduled every 15 minutes by Celery Beat (see beat_schedule in celery_app.py).
    Task name must match the beat_schedule entry exactly:
        app.backend.tasks.parser_task.parse_news_task
    """
    attempt = self.request.retries + 1
    LOG.info(
        "[PARSER] parse_news_task started — attempt=%d, request_id=%s, dry_run=False",
        attempt,
        self.request.id,
    )
    try:
        # Import at runtime to keep Celery worker startup resilient to optional deps.
        from app.backend.services.parser import run_parser

        # dry_run=False ensures data is actually saved to the raw_news table.
        result = run_parser(per_rss_limit=5, per_site_limit=10, dry_run=False)
        saved_count = result.get("saved", 0) if isinstance(result, dict) else 0
        LOG.info(
            "[PARSER] parse_news_task finished — saved=%d, result=%s",
            saved_count,
            result,
        )
        return {"status": "ok", "saved": saved_count, "detail": result}
    except Exception as e:
        LOG.exception("[PARSER] parse_news_task failed on attempt %d: %s", attempt, e)
        raise
