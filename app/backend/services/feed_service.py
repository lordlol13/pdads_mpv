from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def get_user_feed(session: AsyncSession, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    query = """
    SELECT
        uf.id AS user_feed_id,
        uf.user_id,
        uf.ai_news_id,
        uf.ai_score,
        uf.created_at,
        an.raw_news_id,
        an.target_persona,
        an.final_title,
        an.final_text,
        an.category,
        an.vector_status
    FROM user_feed uf
    JOIN ai_news an ON an.id = uf.ai_news_id
    WHERE uf.user_id = :user_id
    ORDER BY uf.ai_score DESC, uf.id DESC
    LIMIT :limit
    """
    result = await session.execute(text(query), {"user_id": user_id, "limit": limit})
    return [dict(row) for row in result.mappings().all()]


async def record_interaction(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    query = """
    INSERT INTO interactions (
        user_id, ai_news_id, liked, viewed, watch_time, created_at
    )
    VALUES (
        :user_id, :ai_news_id, :liked, :viewed, :watch_time, NOW()
    )
    RETURNING id, user_id, ai_news_id, liked, viewed, watch_time, created_at
    """
    result = await session.execute(text(query), payload)
    await session.commit()
    row = result.mappings().first()
    return dict(row) if row is not None else {"id": -1, "status": "created"}
