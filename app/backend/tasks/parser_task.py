from __future__ import annotations
from typing import Any
import logging

from app.backend.core.celery_app import celery_app
from brain.tasks.pipeline_tasks import process_raw_news

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
    LOG.info("[PARSER] parse_news_task started - saving to DB (dry_run=False)")
    try:
        # import at runtime to keep Celery worker startup resilient
        from app.backend.services.parser import run_parser
        from app.backend.db.session import SessionLocal
        from sqlalchemy import text

        # CRITICAL: dry_run=False ensures data is actually saved to raw_news table
        result = run_parser(per_rss_limit=5, per_site_limit=10, dry_run=False)
        saved_count = result.get("saved", 0) if isinstance(result, dict) else 0
        LOG.info("[PARSER] parse_news_task finished: saved=%s, result=%s", saved_count, result)
        
        # NOTE: Auto-processing temporarily disabled - use /api/pipeline/process-all endpoint instead
        # This avoids event loop conflicts in eager mode
        # if saved_count > 0:
        #     LOG.info("[PARSER] Auto-processing pending raw_news...")
        #     ... (auto-processing code)
        
        return {"status": "ok", "saved": saved_count, "detail": result}
    except Exception as e:
        LOG.exception("[PARSER] parse_news_task failed: %s", e)
        raise
