import asyncio
import hashlib
import json
import logging
from typing import Optional, Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import SQLAlchemyError

from app.backend.core.celery_app import celery_app
from app.backend.core.config import settings
from app.backend.services.ingestion_service import create_raw_news
from app.backend.services.llm_service import generate_news
from app.backend.services.media_service import fetch_media_urls, canonical_image_key
from app.backend.services.news_api_service import fetch_articles_for_topics
from app.backend.services.recommender_service import refresh_ai_news_embedding
from app.backend.db.session import SessionLocal

logger = logging.getLogger(__name__)


def _extract_image_urls_payload(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]

    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return []
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return []
        if isinstance(decoded, list):
            return [str(item).strip() for item in decoded if str(item).strip()]

    return []


async def _load_reserved_image_keys(session: AsyncSession, exclude_ai_news_id: int | None) -> set[str]:
    query = """
    SELECT image_urls
    FROM ai_news
    WHERE image_urls IS NOT NULL
    """
    params: dict[str, Any] = {}
    if exclude_ai_news_id is not None:
        query += " AND id <> :exclude_ai_news_id"
        params["exclude_ai_news_id"] = exclude_ai_news_id

    result = await session.execute(text(query), params)
    reserved: set[str] = set()
    for row in result.fetchall():
        payload = row[0] if isinstance(row, tuple) else row.image_urls
        for url in _extract_image_urls_payload(payload):
            key = canonical_image_key(url)
            if key:
                reserved.add(key)
    return reserved


def _build_unique_fallback_image_url(seed_base: str, index: int) -> str:
    digest = hashlib.sha1(f"{seed_base}:{index}".encode("utf-8")).hexdigest()[:16]
    return f"https://picsum.photos/seed/{digest}/1280/720"


def _enforce_cross_post_unique_images(
    media_urls: list[str],
    reserved_keys: set[str],
    *,
    limit: int,
    seed_base: str,
) -> list[str]:
    unique_urls: list[str] = []
    local_keys: set[str] = set()

    for raw_url in media_urls:
        url = str(raw_url or "").strip()
        if not url:
            continue
        key = canonical_image_key(url)
        if not key or key in reserved_keys or key in local_keys:
            continue
        unique_urls.append(url)
        local_keys.add(key)
        if len(unique_urls) >= limit:
            return unique_urls

    # Ensure we still return enough media by generating deterministic unique fallbacks.
    fallback_index = 0
    max_attempts = max(24, limit * 8)
    while len(unique_urls) < limit and fallback_index < max_attempts:
        candidate = _build_unique_fallback_image_url(seed_base, fallback_index)
        fallback_index += 1
        key = canonical_image_key(candidate)
        if not key or key in reserved_keys or key in local_keys:
            continue
        unique_urls.append(candidate)
        local_keys.add(key)

    return unique_urls[:limit]


def _normalize_interests_payload(interests: Any) -> dict[str, Any] | None:
    if isinstance(interests, dict):
        return interests
    if isinstance(interests, str) and interests.strip():
        try:
            parsed = json.loads(interests)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None
    return None


def _extract_topics(interests: Any) -> list[str]:
    if not interests:
        return []

    payload = _normalize_interests_payload(interests)
    if payload is not None:
        collected: list[str] = []
        for key in ("all_topics", "topics", "custom_topics"):
            values = payload.get(key)
            if isinstance(values, list):
                collected.extend([str(t).strip().lower() for t in values if str(t).strip()])
        if collected:
            deduped: list[str] = []
            seen: set[str] = set()
            for topic in collected:
                if topic in seen:
                    continue
                seen.add(topic)
                deduped.append(topic)
            return deduped
        return [str(k).strip().lower() for k, v in payload.items() if v]

    if isinstance(interests, list):
        return [str(t).strip().lower() for t in interests if str(t).strip()]
    return []


def _extract_profession(interests: Any) -> str | None:
    payload = _normalize_interests_payload(interests)
    if payload is not None:
        profession = str(payload.get("profession") or "").strip().lower()
        return profession or None
    return None


def _build_target_persona_label(
    topic: str,
    profession: str | None,
    geo: str | None,
    country_code: str | None,
) -> str:
    parts = [topic.strip().lower() or "general"]
    if profession:
        parts.append(profession.strip().lower())
    if geo:
        parts.append(geo.strip().lower())
    if country_code:
        parts.append(country_code.strip().lower())
    return "|".join(parts)

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
        image_url,
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


async def _load_cohort_personas(session: AsyncSession) -> list[dict[str, str | None]]:
    query = """
    SELECT interests, location, country_code
    FROM users
    WHERE is_active = TRUE
    """
    result = await session.execute(text(query))
    rows = [dict(row) for row in result.mappings().all()]

    persona_contexts: list[dict[str, str | None]] = []
    seen_labels: set[str] = set()
    for row in rows:
        interests = row.get("interests")
        geo = str(row.get("location") or "").strip().lower() or None
        country_code = str(row.get("country_code") or "").strip().upper() or None
        profession = _extract_profession(interests)
        topics = _extract_topics(interests) or ["general"]

        for topic in topics:
            label = _build_target_persona_label(topic, profession, geo, country_code)
            if label in seen_labels:
                continue
            seen_labels.add(label)
            persona_contexts.append(
                {
                    "topic": topic,
                    "profession": profession,
                    "geo": geo,
                    "country_code": country_code,
                    "label": label,
                }
            )

    if not persona_contexts:
        return [{"topic": "general", "profession": None, "geo": None, "country_code": None, "label": "general"}]
    return persona_contexts[:6]


async def _generate_with_quality_loop(
    raw_row: dict[str, Any],
    topic: str,
    profession: str | None,
    geo: str | None,
) -> dict[str, Any]:
    best_result: dict[str, Any] | None = None
    for rewrite_round in range(1, settings.PIPELINE_MAX_REWRITE_ROUNDS + 1):
        generated = await generate_news(
            raw_text=raw_row.get("raw_text") or "",
            title=raw_row.get("title") or "",
            category=raw_row.get("category"),
            target_persona=topic,
            region=raw_row.get("region"),
            profession=profession,
            user_geo=geo,
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
    persona_context: dict[str, str | None],
) -> int:
    topic = str(persona_context.get("topic") or "general").strip().lower()
    profession = str(persona_context.get("profession") or "").strip().lower() or None
    geo = str(persona_context.get("geo") or "").strip().lower() or None
    country_code = str(persona_context.get("country_code") or "").strip().upper() or None
    target_persona = str(
        persona_context.get("label") or _build_target_persona_label(topic, profession, geo, country_code)
    ).strip().lower()

    generated = await _generate_with_quality_loop(raw_row, topic, profession, geo)

    params = {
        "raw_news_id": raw_row["id"],
        "target_persona": target_persona,
        "final_title": generated["final_title"],
        "final_text": generated["final_text"],
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

    reserved_image_keys = await _load_reserved_image_keys(session, exclude_ai_news_id=existing_id)
    media_query = " ".join(
        part
        for part in [
            str(raw_row.get("title") or "").strip(),
            topic,
            str(raw_row.get("category") or "").strip().lower() or None,
            geo,
            country_code.lower() if country_code else None,
        ]
        if part
    ).strip()
    media_urls = await fetch_media_urls(
        media_query,
        limit=4,
        source_url=str(raw_row.get("source_url") or "").strip() or None,
        source_image_url=str(raw_row.get("image_url") or "").strip() or None,
    )
    media_urls = _enforce_cross_post_unique_images(
        media_urls,
        reserved_image_keys,
        limit=4,
        seed_base=f"{raw_row['id']}:{target_persona}",
    )

    video_urls: list[str] = []
    is_sqlite = session.get_bind().dialect.name == "sqlite"
    # For sqlite we store JSON text; for Postgres we use native arrays (list)
    params["image_urls"] = json.dumps(media_urls, ensure_ascii=False) if is_sqlite else media_urls
    params["video_urls"] = json.dumps(video_urls, ensure_ascii=False) if is_sqlite else video_urls

    if existing_id is not None:
        update_query = """
        UPDATE ai_news
        SET final_title = :final_title,
            final_text = :final_text,
            image_urls = :image_urls,
            video_urls = :video_urls,
            category = :category,
            ai_score = :ai_score,
            embedding_id = :embedding_id,
            vector_status = :vector_status
        WHERE id = :id
        RETURNING id
        """
        update_result = await session.execute(text(update_query), {**params, "id": existing_id})
        updated_ai_news_id = update_result.scalar_one()
        await refresh_ai_news_embedding(
            session,
            updated_ai_news_id,
            title=str(generated.get("final_title") or ""),
            final_text=str(generated.get("final_text") or ""),
            category=str(generated.get("category") or None),
            target_persona=target_persona,
            raw_text=str(raw_row.get("raw_text") or ""),
            region=str(raw_row.get("region") or None),
        )
        return updated_ai_news_id

    insert_query = """
    INSERT INTO ai_news (
        raw_news_id,
        target_persona,
        final_title,
        final_text,
        image_urls,
        video_urls,
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
        :video_urls,
        :category,
        :ai_score,
        :embedding_id,
        :vector_status
    )
    RETURNING id
    """
    insert_result = await session.execute(text(insert_query), params)
    ai_news_id = insert_result.scalar_one()
    await refresh_ai_news_embedding(
        session,
        ai_news_id,
        title=str(generated.get("final_title") or ""),
        final_text=str(generated.get("final_text") or ""),
        category=str(generated.get("category") or None),
        target_persona=target_persona,
        raw_text=str(raw_row.get("raw_text") or ""),
        region=str(raw_row.get("region") or None),
    )
    return ai_news_id


async def _populate_user_feed_for_ai_news(
    session: AsyncSession,
    *,
    ai_news_id: int,
    ai_score: float,
    target_topic: str,
    target_profession: str | None,
    target_geo: str | None,
    target_country_code: str | None,
) -> int:
    normalized_profession = (target_profession or "").strip().lower()
    normalized_geo = (target_geo or "").strip().lower()
    normalized_country_code = (target_country_code or "").strip().upper()

    is_sqlite = session.get_bind().dialect.name == "sqlite"
    if is_sqlite:
        query = """
        INSERT INTO user_feed (user_id, ai_news_id, ai_score, created_at)
        SELECT
                u.id,
                :ai_news_id,
                :ai_score,
                CURRENT_TIMESTAMP
        FROM users u
        WHERE COALESCE(u.is_active, 1) = 1
            AND (
                :target_topic = 'general'
                OR EXISTS (
                    SELECT 1
                    FROM json_each(
                        CASE
                            WHEN json_valid(COALESCE(u.interests, '{}')) THEN COALESCE(u.interests, '{}')
                            ELSE '{}'
                        END,
                        '$.all_topics'
                    ) jt
                    WHERE LOWER(CAST(jt.value AS TEXT)) = :target_topic
                )
            )
            AND (
                :target_profession = ''
                OR LOWER(
                    COALESCE(
                        json_extract(
                            CASE
                                WHEN json_valid(COALESCE(u.interests, '{}')) THEN COALESCE(u.interests, '{}')
                                ELSE '{}'
                            END,
                            '$.profession'
                        ),
                        ''
                    )
                ) = :target_profession
            )
            AND (
                :target_geo = ''
                OR LOWER(COALESCE(u.location, '')) LIKE ('%' || :target_geo || '%')
            )
            AND (
                :target_country_code = ''
                OR UPPER(COALESCE(u.country_code, '')) = :target_country_code
            )
            AND NOT EXISTS (
                SELECT 1
                FROM user_feed uf
                WHERE uf.user_id = u.id
                    AND uf.ai_news_id = :ai_news_id
            )
        """
    else:
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
                :target_topic = 'general'
                OR (u.interests -> 'all_topics') ? :target_topic
            )
            AND (
                :target_profession = ''
                OR LOWER(COALESCE(u.interests ->> 'profession', '')) = :target_profession
            )
            AND (
                :target_geo = ''
                OR LOWER(COALESCE(u.location, '')) LIKE ('%' || :target_geo || '%')
            )
            AND (
                :target_country_code = ''
                OR UPPER(COALESCE(u.country_code, '')) = :target_country_code
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
            "target_topic": target_topic,
            "target_profession": normalized_profession,
            "target_geo": normalized_geo,
            "target_country_code": normalized_country_code,
        },
    )
    return int(result.rowcount or 0)


async def _schedule_ingestion_batch_async() -> dict[str, Any]:
    async with SessionLocal() as session:
        persona_contexts = await _load_cohort_personas(session)
        topics = list(dict.fromkeys([str(p.get("topic") or "general") for p in persona_contexts]))
        country_codes = [str(p.get("country_code") or "").strip().upper() for p in persona_contexts if p.get("country_code")]
        articles = await fetch_articles_for_topics(
            topics,
            settings.NEWS_FETCH_BATCH_SIZE,
            country_codes=country_codes,
        )

        if not articles and "general" not in topics:
            articles = await fetch_articles_for_topics(
                [*topics, "general"],
                settings.NEWS_FETCH_BATCH_SIZE,
                country_codes=country_codes,
            )

        queued = 0
        for article in articles:
            raw_news = await create_raw_news(session, article)
            if raw_news.get("process_status") in {"pending", "failed", None}:
                process_raw_news.delay(raw_news["id"], persona_contexts)
                queued += 1

        return {
            "fetched": len(articles),
            "queued": queued,
            "personas": [str(p.get("label") or p.get("topic") or "general") for p in persona_contexts],
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


async def _process_raw_news_async(
    raw_news_id: int,
    attempt: int,
    personas: list[dict[str, str | None]] | None = None,
) -> dict:
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
            for persona_context in cohort_personas:
                ai_news_id = await _upsert_ai_news_for_persona(session, raw_row, persona_context)
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
                    target_topic=str(persona_context.get("topic") or "general"),
                    target_profession=str(persona_context.get("profession") or "").strip().lower() or None,
                    target_geo=str(persona_context.get("geo") or "").strip().lower() or None,
                    target_country_code=str(persona_context.get("country_code") or "").strip().upper() or None,
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
                "personas": [str(item.get("label") or item.get("topic") or "general") for item in cohort_personas],
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
    autoretry_for=(ConnectionError, TimeoutError, Exception),
    retry_backoff=True,
    retry_backoff_max=settings.API_RETRY_MAX_DELAY_SECONDS,
    retry_backoff_base=2,
    retry_jitter=True,
    max_retries=settings.API_RETRY_MAX_ATTEMPTS,
)
def process_raw_news(self, raw_news_id: int, personas: list[dict[str, str | None]] | None = None) -> dict:
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


@celery_app.task(
    name="brain.scheduled_ingestion",
    autoretry_for=(ConnectionError, TimeoutError, Exception),
    retry_backoff=True,
    retry_backoff_max=settings.API_RETRY_MAX_DELAY_SECONDS,
    retry_jitter=True,
    max_retries=2,  # Scheduled tasks - limited retries
)
def scheduled_ingestion() -> dict:
    logger.info("scheduled_ingestion tick started")
    try:
        result = asyncio.run(_schedule_ingestion_batch_async())
        logger.info("scheduled_ingestion tick finished result=%s", result)
        return result
    except Exception as e:
        logger.error("scheduled_ingestion failed: %s", e)
        raise


@celery_app.task(
    name="brain.scheduled_cleanup_ai_products",
    autoretry_for=(ConnectionError, TimeoutError, Exception),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=1,  # Cleanup is low priority
)
def scheduled_cleanup_ai_products() -> dict:
    logger.info("scheduled_cleanup_ai_products tick started")
    try:
        result = asyncio.run(_cleanup_ai_products_async())
        logger.info("scheduled_cleanup_ai_products tick finished result=%s", result)
        return result
    except Exception as e:
        logger.error("scheduled_cleanup_ai_products failed: %s", e)
        raise
