"""Feed loader - loads fresh ai_news candidates without personalization."""

from typing import Any
from datetime import datetime, timedelta

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.core.logging import ContextLogger

logger = ContextLogger(__name__)

# Freshness threshold in hours
DEFAULT_FRESHNESS_HOURS = 48


async def load_fresh_candidates(
    session: AsyncSession,
    user_id: int,
    limit: int,
    freshness_hours: int = DEFAULT_FRESHNESS_HOURS,
) -> list[dict[str, Any]]:
    """
    Load fresh ai_news candidates.
    
    This is the SOURCE of truth for feed generation.
    NO personalization logic here - purely data loading.
    
    Returns candidates ordered by recency and quality score.
    """
    cutoff = datetime.utcnow() - timedelta(hours=freshness_hours)
    query = """
    SELECT
        an.id AS ai_news_id,
        an.raw_news_id,
        an.target_persona,
        an.final_title,
        an.final_text,
        rn.source_url AS source_url,
        an.image_urls,
        an.video_urls,
        an.category,
        rn.region,
        an.ai_score,
        an.vector_status,
        TRUE AS is_ai,
        an.created_at,
        COALESCE(an.ai_score, 0) AS base_score
    FROM ai_news an
    LEFT JOIN raw_news rn ON rn.id = an.raw_news_id
    WHERE an.created_at >= :cutoff
      AND an.final_title IS NOT NULL
      AND an.final_text IS NOT NULL
      AND LENGTH(TRIM(an.final_title)) > 0
      AND LENGTH(TRIM(an.final_text)) > 0
    ORDER BY an.ai_score DESC, an.created_at DESC
    LIMIT :limit_param
    """
    
    result = await session.execute(
        text(query),
        {"limit_param": max(limit * 5, 250), "cutoff": cutoff}
    )
    candidates = [dict(row) for row in result.mappings().all()]

    for candidate in candidates:
        image_url = candidate.get("image_url")
        if image_url:
            continue
        image_urls = candidate.get("image_urls")
        if isinstance(image_urls, list) and image_urls:
            candidate["image_url"] = image_urls[0]
    
    logger.info(
        "loaded_candidates",
        extra={
            "user_id": user_id,
            "count": len(candidates),
            "freshness_hours": freshness_hours,
        }
    )
    
    return candidates


async def load_user_interactions(
    session: AsyncSession,
    user_id: int,
    ai_news_ids: list[int],
) -> dict[int, dict[str, Any]]:
    """
    Load user's interaction history for these items.
    
    Returns a dict mapping ai_news_id -> {liked, saved, viewed, etc}
    Optional enrichment - not required for feed generation.
    """
    if not ai_news_ids:
        return {}
    
    query = """
    WITH latest_user_interactions AS (
        SELECT *
        FROM (
            SELECT
                i.*,
                ROW_NUMBER() OVER (
                    PARTITION BY i.user_id, i.ai_news_id
                    ORDER BY i.created_at DESC, i.id DESC
                ) AS rn
            FROM interactions i
            WHERE i.user_id = :user_id
        ) ranked
        WHERE rn = 1
    ),
    latest_likes AS (
        SELECT ai_news_id, COUNT(*) AS like_count
        FROM (
            SELECT
                i.user_id,
                i.ai_news_id,
                i.liked,
                ROW_NUMBER() OVER (
                    PARTITION BY i.user_id, i.ai_news_id
                    ORDER BY i.created_at DESC, i.id DESC
                ) AS rn
            FROM interactions i
            WHERE i.ai_news_id IN :ids
        ) ranked
        WHERE rn = 1 AND COALESCE(liked, FALSE) = TRUE
        GROUP BY ai_news_id
    ),
    liked_topics AS (
        SELECT DISTINCT LOWER(TRIM(an.category)) AS category
        FROM latest_user_interactions lui
        JOIN ai_news an ON an.id = lui.ai_news_id
        WHERE COALESCE(lui.liked, FALSE) = TRUE
          AND an.category IS NOT NULL
          AND LENGTH(TRIM(an.category)) > 0
    ),
    comment_counts AS (
        SELECT ai_news_id, COUNT(*) AS comment_count
        FROM feed_comments
        WHERE ai_news_id IN :ids
        GROUP BY ai_news_id
    ),
    skipped_items AS (
        SELECT DISTINCT ai_news_id
        FROM user_events
        WHERE user_id = :user_id
          AND ai_news_id IN :ids
          AND event_type = 'skip'
    )
    SELECT
        an.id AS ai_news_id,
        COALESCE(lui.liked, FALSE) AS liked,
        COALESCE(lui.viewed, FALSE) AS viewed,
        COALESCE(sn.id IS NOT NULL, FALSE) AS saved,
        COALESCE(ll.like_count, 0) AS like_count,
        COALESCE(cc.comment_count, 0) AS comment_count,
        COALESCE(lt.category IS NOT NULL, FALSE) AS topic_liked,
        COALESCE(si.ai_news_id IS NOT NULL, FALSE) AS skipped,
        lui.created_at
    FROM ai_news an
    LEFT JOIN latest_user_interactions lui
        ON lui.ai_news_id = an.id
    LEFT JOIN saved_news sn
        ON sn.user_id = :user_id
       AND sn.ai_news_id = an.id
    LEFT JOIN latest_likes ll
        ON ll.ai_news_id = an.id
    LEFT JOIN comment_counts cc
        ON cc.ai_news_id = an.id
    LEFT JOIN liked_topics lt
        ON lt.category = LOWER(TRIM(an.category))
    LEFT JOIN skipped_items si
        ON si.ai_news_id = an.id
    WHERE an.id IN :ids
    """
    
    result = await session.execute(
        text(query).bindparams(bindparam("ids", expanding=True)),
        {"user_id": user_id, "ids": ai_news_ids}
    )
    
    interactions = {}
    for row in result.mappings().all():
        ai_news_id = int(row["ai_news_id"])
        interactions[ai_news_id] = {
            **dict(row),
            "liked": bool(row.get("liked")),
            "viewed": bool(row.get("viewed")),
        }
    
    return interactions
