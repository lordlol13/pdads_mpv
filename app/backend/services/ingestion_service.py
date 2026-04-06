import hashlib
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.db.sql_helpers import sql_timestamp_now


def build_content_hash(title: str, raw_text: str | None, source_url: str | None) -> str:
    payload = "|".join([title.strip(), (raw_text or "").strip(), (source_url or "").strip()])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


async def create_raw_news(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    content_hash = build_content_hash(
        payload["title"],
        payload.get("raw_text"),
        payload.get("source_url"),
    )

    existing_query = """
    SELECT
        id, title, source_url, raw_text, category, region, is_urgent,
        created_at, process_status, error_message, attempt_count, content_hash
    FROM raw_news
    WHERE content_hash = :content_hash
    ORDER BY id
    LIMIT 1
    """
    existing_result = await session.execute(text(existing_query), {"content_hash": content_hash})
    existing_row = existing_result.mappings().first()
    if existing_row is not None:
        return dict(existing_row)

    now_sql = sql_timestamp_now(session)
    insert_query = f"""
    INSERT INTO raw_news (
        title, source_url, raw_text, category, region, is_urgent,
        created_at, process_status, error_message, attempt_count, content_hash
    )
    VALUES (
        :title, :source_url, :raw_text, :category, :region, :is_urgent,
        {now_sql}, 'pending', NULL, 0, :content_hash
    )
    RETURNING
        id, title, source_url, raw_text, category, region, is_urgent,
        created_at, process_status, error_message, attempt_count, content_hash
    """
    result = await session.execute(
        text(insert_query),
        {
            "title": payload["title"],
            "source_url": payload.get("source_url"),
            "raw_text": payload.get("raw_text"),
            "category": payload.get("category"),
            "region": payload.get("region"),
            "is_urgent": payload.get("is_urgent", False),
            "content_hash": content_hash,
        },
    )
    await session.commit()
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create raw news")
    return dict(row)
