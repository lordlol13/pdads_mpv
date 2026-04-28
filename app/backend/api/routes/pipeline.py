from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
import logging

LOG = logging.getLogger(__name__)

from app.backend.core.celery_app import celery_app
from app.backend.db.session import SessionLocal
from app.backend.schemas.pipeline import (
    EnqueueResponse,
    TaskStatusResponse,
    RawNewsItem,
    AiNewsItem,
)
from app.backend.tasks.parser_task import parse_news_task
from app.backend.services.parser import run_parser_async
from brain.tasks.pipeline_tasks import process_raw_news, _process_raw_news_async

router = APIRouter(prefix="/pipeline", tags=["pipeline"])


@router.post("/parse")
async def trigger_parse():
    """Trigger news parser task. Returns result immediately in eager mode, or task_id in async mode."""
    try:
        if celery_app.conf.task_always_eager:
            # Dev mode: we're in FastAPI's event loop, use await directly
            # (don't use parse_news_task() which creates a new event loop)
            result = await run_parser_async(per_rss_limit=5, per_site_limit=10, dry_run=False)
            return {
                "status": "completed",
                "result": result
            }
        else:
            # Production mode: enqueue to Celery worker
            task = parse_news_task.delay()
            return {
                "status": "queued",
                "task_id": task.id
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process-all")
async def process_all_pending():
    """Process all raw_news with status 'pending'. Returns count of queued items."""
    try:
        # Get all pending raw_news
        query = """
        SELECT id
        FROM raw_news
        WHERE process_status = 'pending'
        ORDER BY id DESC
        """
        async with SessionLocal() as session:
            result = await session.execute(text(query))
            pending_ids = [row[0] for row in result.fetchall()]
        
        LOG.info("[PROCESS-ALL] Found %s pending raw_news", len(pending_ids))
        
        if not pending_ids:
            return {
                "status": "completed",
                "queued": 0,
                "message": "No pending raw_news to process"
            }
        
        # Queue processing for each
        queued = 0
        errors = []
        
        if celery_app.conf.task_always_eager:
            # Dev mode: call async function directly (we're already in FastAPI's event loop)
            LOG.info("[PROCESS-ALL] Eager mode: processing %s items", len(pending_ids))
            for raw_id in pending_ids:
                try:
                    LOG.info("[PROCESS-ALL] Processing raw_news_id=%s", raw_id)
                    result = await _process_raw_news_async(raw_id, attempt=1)
                    LOG.info("[PROCESS-ALL] Success raw_news_id=%s", raw_id)
                    queued += 1
                except Exception as e:
                    LOG.exception("[PROCESS-ALL] Exception raw_news_id=%s: %s", raw_id, e)
                    errors.append(f"{raw_id}: {e}")
        else:
            # Production mode: enqueue to Celery
            LOG.info("[PROCESS-ALL] Async mode: queueing %s items", len(pending_ids))
            for raw_id in pending_ids:
                try:
                    LOG.info("[PROCESS-ALL] Queueing raw_news_id=%s", raw_id)
                    process_raw_news.delay(raw_id)
                    queued += 1
                except Exception as e:
                    LOG.exception("[PROCESS-ALL] Failed to queue raw_news_id=%s: %s", raw_id, e)
                    errors.append(f"{raw_id}: {e}")
        
        LOG.info("[PROCESS-ALL] Finished: queued=%s, total=%s, errors=%s", queued, len(pending_ids), len(errors))
        
        return {
            "status": "completed" if celery_app.conf.task_always_eager else "queued",
            "queued": queued,
            "total_pending": len(pending_ids),
            "errors": errors if errors else None
        }
    except Exception as e:
        LOG.exception("[PROCESS-ALL] Fatal error: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/process/{raw_news_id}", response_model=EnqueueResponse)
def enqueue_process_raw_news(raw_news_id: int):
    if raw_news_id <= 0:
        raise HTTPException(status_code=400, detail="raw_news_id must be > 0")
    task = celery_app.send_task("brain.process_raw_news", args=[raw_news_id])
    return EnqueueResponse(task_id=task.id, raw_news_id=raw_news_id, status="queued")


@router.get("/tasks/{task_id}", response_model=TaskStatusResponse)
def get_task_status(task_id: str):
    res = celery_app.AsyncResult(task_id)
    payload = res.result if isinstance(res.result, dict) else None
    return TaskStatusResponse(task_id=task_id, state=res.state, result=payload)


@router.get("/raw-news", response_model=list[RawNewsItem])
async def list_raw_news(limit: int = Query(default=50, ge=1, le=200)):
    query = """
    SELECT
        id, title, source_url, image_url, raw_text, category, region, is_urgent,
        process_status, error_message, attempt_count, created_at
    FROM raw_news
    ORDER BY id DESC
    LIMIT :limit
    """
    async with SessionLocal() as session:
        result = await session.execute(text(query), {"limit": limit})
        return [RawNewsItem(**dict(row)) for row in result.mappings().all()]


@router.get("/ai-news", response_model=list[AiNewsItem])
async def list_ai_news(limit: int = Query(default=50, ge=1, le=200)):
    query = """
    SELECT
        id, raw_news_id, target_persona, final_title, final_text,
        image_urls, video_urls,
        category, ai_score, vector_status, created_at
    FROM ai_news
    ORDER BY id DESC
    LIMIT :limit
    """
    async with SessionLocal() as session:
        result = await session.execute(text(query), {"limit": limit})
        return [AiNewsItem(**dict(row)) for row in result.mappings().all()]


@router.post("/admin/reset")
async def admin_reset():
    """Admin endpoint to reset the pipeline state.
    
    - Clears all ai_news records
    - Resets raw_news.process_status to 'pending'
    - Resets attempt_count to 0
    """
    try:
        async with SessionLocal() as session:
            # Delete all ai_news records
            delete_ai_query = "DELETE FROM ai_news"
            result_ai = await session.execute(text(delete_ai_query))
            deleted_ai = result_ai.rowcount
            
            # Reset raw_news status to pending
            update_raw_query = """
            UPDATE raw_news 
            SET process_status = 'pending', 
                error_message = NULL, 
                attempt_count = 0
            WHERE process_status IN ('processed', 'failed', 'error')
            """
            result_raw = await session.execute(text(update_raw_query))
            updated_raw = result_raw.rowcount
            
            await session.commit()
            
            LOG.info(f"[ADMIN-RESET] Deleted {deleted_ai} ai_news, reset {updated_raw} raw_news to pending")
            
            return {
                "status": "success",
                "deleted_ai_news": deleted_ai,
                "reset_raw_news": updated_raw,
                "message": "Pipeline state reset successfully"
            }
    except Exception as e:
        LOG.exception(f"[ADMIN-RESET] Error: {e}")
        raise HTTPException(status_code=500, detail=str(e))