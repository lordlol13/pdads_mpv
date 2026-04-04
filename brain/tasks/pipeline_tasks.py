import asyncio
import logging
from typing import Optional, Mapping, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession

from app.backend.core.celery_app import celery_app
from app.backend.core.config import settings

logger = logging.getLogger(__name__)

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    future=True,
)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def _set_status(
    session: AsyncSession,
    raw_news_id: int,
    status: str,
    error_message: Optional[str] = None,
    attempt_count: Optional[int] = None,
) -> None:
    query = """
    UPDATE raw_news
    SET process_status = :status,
        error_message = :error_message,
        attempt_count = COALESCE(:attempt_count, attempt_count)
    WHERE id = :raw_news_id
    """
    await session.execute(
        text(query),
        {
            "status": status,
            "error_message": error_message,
            "attempt_count": attempt_count,
            "raw_news_id": raw_news_id,
        },
    )


async def _fetch_raw_news(session: AsyncSession, raw_news_id: int) -> Optional[Mapping[str, Any]]:
    query = """
    SELECT
        id,
        title,
        raw_text,
        source_url,
        category,
        region,
        is_urgent
    FROM raw_news
    WHERE id = :raw_news_id
    """
    result = await session.execute(text(query), {"raw_news_id": raw_news_id})
    row = result.mappings().first()
    if row is None:
        return None
    return dict(row)


async def _insert_ai_news(session: AsyncSession, raw_row: Mapping[str, Any]) -> int:
    final_title = f"[AI] {raw_row['title']}"
    final_text = (raw_row.get("raw_text") or "")[:1200]
    target_persona = "general"
    ai_score = 8.5
    vector_status = "pending"

    params = {
        "raw_news_id": raw_row["id"],
        "target_persona": target_persona,
        "final_title": final_title,
        "final_text": final_text,
        "image_urls": [],
        "category": raw_row.get("category"),
        "ai_score": ai_score,
        "embedding_id": None,
        "vector_status": vector_status,
    }

    select_existing_query = """
    SELECT id
    FROM ai_news
    WHERE raw_news_id = :raw_news_id
      AND target_persona = :target_persona
    ORDER BY id
    LIMIT 1
    """
    existing_result = await session.execute(text(select_existing_query), params)
    existing_id = existing_result.scalar_one_or_none()

    if existing_id is not None:
        update_query = """
        UPDATE ai_news
        SET final_title = :final_title,
            final_text = :final_text,
            image_urls = :image_urls,
            category = :category,
            ai_score = :ai_score,
            embedding_id = :embedding_id,
            vector_status = :vector_status
        WHERE id = :id
        RETURNING id
        """
        update_result = await session.execute(text(update_query), {**params, "id": existing_id})
        return update_result.scalar_one()

    insert_query = """
    INSERT INTO ai_news (
        raw_news_id,
        target_persona,
        final_title,
        final_text,
        image_urls,
        category,
        ai_score,
        embedding_id,
        vector_status
    )
    VALUES (
        :raw_news_id,
        :target_persona,
        :final_title,
        :final_text,
        :image_urls,
        :category,
        :ai_score,
        :embedding_id,
        :vector_status
    )
    RETURNING id
    """
    insert_result = await session.execute(text(insert_query), params)
    return insert_result.scalar_one()
async def _process_raw_news_async(raw_news_id: int, attempt: int) -> dict:
    async with SessionLocal() as session:
        await _set_status(
            session=session,
            raw_news_id=raw_news_id,
            status="classified",
            error_message=None,
            attempt_count=attempt,
        )
        await session.commit()

        raw_row = await _fetch_raw_news(session, raw_news_id)
        if not raw_row:
            await _set_status(
                session=session,
                raw_news_id=raw_news_id,
                status="failed",
                error_message=f"raw_news id={raw_news_id} not found",
                attempt_count=attempt,
            )
            await session.commit()
            return {"status": "failed", "reason": "raw_news_not_found", "raw_news_id": raw_news_id}

        ai_news_id = await _insert_ai_news(session, raw_row)

        await _set_status(
            session=session,
            raw_news_id=raw_news_id,
            status="generated",
            error_message=None,
            attempt_count=attempt,
        )
        await session.commit()

        return {"status": "generated", "raw_news_id": raw_news_id, "ai_news_id": ai_news_id}


@celery_app.task(
    name="brain.process_raw_news",
    bind=True,
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    retry_kwargs={"max_retries": 5},
)
def process_raw_news(self, raw_news_id: int) -> dict:
    attempt = self.request.retries + 1
    logger.info("process_raw_news started raw_news_id=%s attempt=%s", raw_news_id, attempt)

    try:
        result = asyncio.run(_process_raw_news_async(raw_news_id, attempt))
        logger.info("process_raw_news finished raw_news_id=%s result=%s", raw_news_id, result)
        return result

    except Exception as e:
        logger.exception("process_raw_news failed raw_news_id=%s attempt=%s error=%s", raw_news_id, attempt, e)

        # фиксируем failed в БД даже при неожиданных ошибках
        async def _mark_failed():
            async with SessionLocal() as session:
                await _set_status(
                    session=session,
                    raw_news_id=raw_news_id,
                    status="failed",
                    error_message=str(e)[:2000],
                    attempt_count=attempt,
                )
                await session.commit()

        try:
            asyncio.run(_mark_failed())
        except Exception:
            logger.exception("failed to persist failed status for raw_news_id=%s", raw_news_id)

        raise