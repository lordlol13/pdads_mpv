import asyncio
import logging
from typing import Optional, Any
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.exc import SQLAlchemyError
from app.backend.core.celery_app import celery_app
from app.backend.core.config import settings
from app.backend.services.llm_service import generate_news

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


async def _fetch_raw_news(session: AsyncSession, raw_news_id: int) -> Optional[dict[str, Any]]:
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


async def _upsert_ai_news(session: AsyncSession, raw_row: dict[str, Any]) -> int:
    generated = await generate_news(
        raw_text=raw_row.get("raw_text") or "",
        title=raw_row.get("title") or "",
        category=raw_row.get("category"),
    )

    params = {
        "raw_news_id": raw_row["id"],
        "target_persona": generated["target_persona"],
        "final_title": generated["final_title"],
        "final_text": generated["final_text"],
        "image_urls": [],
        "category": generated["category"],
        "ai_score": generated["ai_score"],
        "embedding_id": None,
        "vector_status": "pending",
    }

    existing_query = """
    SELECT id
    FROM ai_news
    WHERE raw_news_id = :raw_news_id
      AND target_persona = :target_persona
    ORDER BY id
    LIMIT 1
    """
    existing_result = await session.execute(text(existing_query), params)
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
        try:
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

            ai_news_id = await _upsert_ai_news(session, raw_row)

            await _set_status(
                session=session,
                raw_news_id=raw_news_id,
                status="generated",
                error_message=None,
                attempt_count=attempt,
            )
            await session.commit()

            return {"status": "generated", "raw_news_id": raw_news_id, "ai_news_id": ai_news_id}

        except Exception as e:
            await session.rollback()
            try:
                await _set_status(
                    session=session,
                    raw_news_id=raw_news_id,
                    status="failed",
                    error_message=str(e)[:2000],
                    attempt_count=attempt,
                )
                await session.commit()
            except Exception:
                logger.exception("failed to persist failed status raw_news_id=%s", raw_news_id)
            raise


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
    except SQLAlchemyError as e:
        logger.exception("db error raw_news_id=%s attempt=%s error=%s", raw_news_id, attempt, e)
        raise
    except Exception as e:
        logger.exception("unexpected error raw_news_id=%s attempt=%s error=%s", raw_news_id, attempt, e)
        raise