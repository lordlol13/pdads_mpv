from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.api.dependencies import get_db_session
from app.backend.schemas.ingestion import RawNewsCreateRequest, RawNewsCreateResponse
from app.backend.services.ingestion_service import create_raw_news as create_raw_news_record

router = APIRouter(prefix="/ingestion", tags=["ingestion"])


@router.post("/raw-news", response_model=RawNewsCreateResponse)
async def ingest_raw_news(
    payload: RawNewsCreateRequest,
    session: AsyncSession = Depends(get_db_session),
):
    record = await create_raw_news_record(session, payload.model_dump())
    return RawNewsCreateResponse(
        id=record["id"],
        content_hash=record["content_hash"],
        process_status=record.get("process_status"),
        created_at=record.get("created_at"),
    )


@router.get("/raw-news/{raw_news_id}")
async def get_raw_news(raw_news_id: int, session: AsyncSession = Depends(get_db_session)):
    query = """
    SELECT
        id, title, source_url, image_url, raw_text, category, region, is_urgent,
        created_at, process_status, error_message, attempt_count, content_hash
    FROM raw_news
    WHERE id = :raw_news_id
    LIMIT 1
    """
    result = await session.execute(text(query), {"raw_news_id": raw_news_id})
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="raw_news not found")
    return dict(row)
