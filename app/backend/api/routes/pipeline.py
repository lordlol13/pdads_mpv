from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.backend.core.config import settings
from app.backend.core.celery_app import celery_app
from app.backend.schemas.pipeline import (
    EnqueueResponse,
    TaskStatusResponse,
    RawNewsItem,
    AiNewsItem,
)

router = APIRouter(prefix="/pipeline", tags=["pipeline"])

engine = create_async_engine(settings.DATABASE_URL, echo=False, pool_pre_ping=True, future=True)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


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
        id, title, source_url, raw_text, category, region, is_urgent,
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
        category, ai_score, vector_status, created_at
    FROM ai_news
    ORDER BY id DESC
    LIMIT :limit
    """
    async with SessionLocal() as session:
        result = await session.execute(text(query), {"limit": limit})
        return [AiNewsItem(**dict(row)) for row in result.mappings().all()]