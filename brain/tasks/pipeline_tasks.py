import asyncio
import logging
from typing import Optional, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.backend.core.celery_app import celery_app
from app.backend.core.config import settings
from app.backend.services.ingestion_service import create_raw_news
from app.backend.services.llm_service import generate_news
from app.backend.services.media_service import fetch_media_urls
from app.backend.services.news_api_service import fetch_articles_for_topics
from app.backend.db.session import SessionLocal

logger = logging.getLogger(__name__)

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
    return await _upsert_ai_news_for_persona(session, raw_row, "general")


def _extract_topics(interests: Any) -> list[str]:
    if not interests:
        return []
    if isinstance(interests, dict):
        if isinstance(interests.get("topics"), list):
            return [str(t).strip().lower() for t in interests["topics"] if str(t).strip()]
        return [str(k).strip().lower() for k, v in interests.items() if v]
    if isinstance(interests, list):
        return [str(t).strip().lower() for t in interests if str(t).strip()]
    return []


async def _load_cohort_personas(session: AsyncSession) -> list[str]:
    query = """
    SELECT interests
    FROM users
    WHERE is_active = TRUE
    """
    result = await session.execute(text(query))
    interests_rows = [dict(row).get("interests") for row in result.mappings().all()]

    personas: list[str] = []
    for interests in interests_rows:
        for topic in _extract_topics(interests):
            if topic not in personas:
                personas.append(topic)

    return personas[:6] if personas else ["general"]


async def _generate_with_quality_loop(raw_row: dict[str, Any], target_persona: str) -> dict[str, Any]:
    best_result: dict[str, Any] | None = None
    for rewrite_round in range(1, settings.PIPELINE_MAX_REWRITE_ROUNDS + 1):
        generated = await generate_news(
            raw_text=raw_row.get("raw_text") or "",
            title=raw_row.get("title") or "",
            category=raw_row.get("category"),
            target_persona=target_persona,
            region=raw_row.get("region"),
            rewrite_round=rewrite_round,
        )

        combined_score = float(generated.get("combined_score", generated.get("ai_score", 0.0)))
        if best_result is None or combined_score > float(best_result.get("combined_score", 0.0)):
            best_result = generated

        if combined_score >= settings.PIPELINE_TARGET_SCORE:
            return generated

    if best_result is None:
        raise ValueError("generation_failed")

    if float(best_result.get("combined_score", 0.0)) < settings.PIPELINE_MIN_SCORE:
        raise ValueError(
            f"low_generation_score:{best_result.get('combined_score')}"
        )

    return best_result


async def _upsert_ai_news_for_persona(
    session: AsyncSession,
    raw_row: dict[str, Any],
    target_persona: str,
) -> int:
    generated = await _generate_with_quality_loop(raw_row, target_persona)
    media_urls = await fetch_media_urls(f"{raw_row.get('title') or ''} {target_persona}", limit=5)

    params = {
        "raw_news_id": raw_row["id"],
        "target_persona": target_persona,
        "final_title": generated["final_title"],
        "final_text": generated["final_text"],
        "image_urls": media_urls,
        "category": generated["category"],
        "ai_score": generated["combined_score"],
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


async def _populate_user_feed_for_ai_news(
        session: AsyncSession,
        *,
        ai_news_id: int,
        ai_score: float,
        target_persona: str,
) -> int:
        query = """
        INSERT INTO user_feed (user_id, ai_news_id, ai_score, created_at)
        SELECT
                u.id,
                :ai_news_id,
                :ai_score,
                NOW()
        FROM users u
        WHERE u.is_active = TRUE
            AND (
                :target_persona = 'general'
                OR (u.interests -> 'topics') ? :target_persona
            )
            AND NOT EXISTS (
                SELECT 1
                FROM user_feed uf
                WHERE uf.user_id = u.id
                    AND uf.ai_news_id = :ai_news_id
            )
        """
        result = await session.execute(
                text(query),
                {
                        "ai_news_id": ai_news_id,
                        "ai_score": ai_score,
                        "target_persona": target_persona,
                },
        )
        return int(result.rowcount or 0)


async def _schedule_ingestion_batch_async() -> dict[str, Any]:
    async with SessionLocal() as session:
        personas = await _load_cohort_personas(session)
        articles = await fetch_articles_for_topics(personas, settings.NEWS_FETCH_BATCH_SIZE)

        queued = 0
        for article in articles:
            raw_news = await create_raw_news(session, article)
            if raw_news.get("process_status") in {"pending", "failed", None}:
                process_raw_news.delay(raw_news["id"], personas)
                queued += 1

        return {
            "fetched": len(articles),
            "queued": queued,
            "personas": personas,
        }


async def _cleanup_ai_products_async() -> dict[str, Any]:
    async with SessionLocal() as session:
        query = """
        DELETE FROM ai_news
        WHERE created_at < NOW() - make_interval(days => :retention_days)
        """
        result = await session.execute(
            text(query),
            {"retention_days": settings.AI_PRODUCT_RETENTION_DAYS},
        )
        await session.commit()
        deleted = int(result.rowcount or 0)
        return {
            "deleted_ai_news": deleted,
            "retention_days": settings.AI_PRODUCT_RETENTION_DAYS,
        }


async def _process_raw_news_async(raw_news_id: int, attempt: int, personas: list[str] | None = None) -> dict:
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

            cohort_personas = personas or await _load_cohort_personas(session)
            ai_news_ids: list[int] = []
            for persona in cohort_personas:
                ai_news_id = await _upsert_ai_news_for_persona(session, raw_row, persona)
                ai_news_ids.append(ai_news_id)
                score_result = await session.execute(
                    text("SELECT ai_score FROM ai_news WHERE id = :id"),
                    {"id": ai_news_id},
                )
                ai_score = float(score_result.scalar_one_or_none() or 0.0)
                await _populate_user_feed_for_ai_news(
                    session,
                    ai_news_id=ai_news_id,
                    ai_score=ai_score,
                    target_persona=persona,
                )

            await _set_status(
                session=session,
                raw_news_id=raw_news_id,
                status="generated",
                error_message=None,
                attempt_count=attempt,
            )
            await session.commit()

            return {
                "status": "generated",
                "raw_news_id": raw_news_id,
                "ai_news_ids": ai_news_ids,
                "personas": cohort_personas,
            }

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
def process_raw_news(self, raw_news_id: int, personas: list[str] | None = None) -> dict:
    attempt = self.request.retries + 1
    logger.info("process_raw_news started raw_news_id=%s attempt=%s", raw_news_id, attempt)

    try:
        result = asyncio.run(_process_raw_news_async(raw_news_id, attempt, personas))
        logger.info("process_raw_news finished raw_news_id=%s result=%s", raw_news_id, result)
        return result
    except SQLAlchemyError as e:
        logger.exception("db error raw_news_id=%s attempt=%s error=%s", raw_news_id, attempt, e)
        raise
    except Exception as e:
        logger.exception("unexpected error raw_news_id=%s attempt=%s error=%s", raw_news_id, attempt, e)
        raise


@celery_app.task(name="brain.scheduled_ingestion")
def scheduled_ingestion() -> dict:
    logger.info("scheduled_ingestion tick started")
    result = asyncio.run(_schedule_ingestion_batch_async())
    logger.info("scheduled_ingestion tick finished result=%s", result)
    return result


@celery_app.task(name="brain.scheduled_cleanup_ai_products")
def scheduled_cleanup_ai_products() -> dict:
    logger.info("scheduled_cleanup_ai_products tick started")
    result = asyncio.run(_cleanup_ai_products_async())
    logger.info("scheduled_cleanup_ai_products tick finished result=%s", result)
    return result