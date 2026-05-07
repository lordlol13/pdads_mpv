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

    unique_ids = [int(news_id) for news_id in dict.fromkeys(ai_news_ids) if int(news_id or 0) > 0]
    if not unique_ids:
        return {}

    interactions_query = (
        text(
            """
            SELECT
                ai_news_id,
                MAX(CASE WHEN liked IS TRUE THEN 1 WHEN liked IS FALSE THEN -1 ELSE 0 END) AS like_state,
                BOOL_OR(COALESCE(viewed, FALSE)) AS viewed,
                MAX(COALESCE(watch_time, 0)) AS watch_time
            FROM interactions
            WHERE user_id = :user_id
              AND ai_news_id IN :ai_news_ids
            GROUP BY ai_news_id
            """
        ).bindparams(bindparam("ai_news_ids", expanding=True))
    )
    saved_query = (
        text(
            """
            SELECT ai_news_id
            FROM saved_news
            WHERE user_id = :user_id
              AND ai_news_id IN :ai_news_ids
            """
        ).bindparams(bindparam("ai_news_ids", expanding=True))
    )
    comments_query = (
        text(
            """
            SELECT ai_news_id, COUNT(*) AS comment_count
            FROM feed_comments
            WHERE ai_news_id IN :ai_news_ids
            GROUP BY ai_news_id
            """
        ).bindparams(bindparam("ai_news_ids", expanding=True))
    )

    interactions_result = await session.execute(interactions_query, {"user_id": user_id, "ai_news_ids": unique_ids})
    saved_result = await session.execute(saved_query, {"user_id": user_id, "ai_news_ids": unique_ids})
    comments_result = await session.execute(comments_query, {"ai_news_ids": unique_ids})

    saved_ids = {int(row[0]) for row in saved_result.fetchall()}
    comment_counts = {int(row[0]): int(row[1] or 0) for row in comments_result.fetchall()}

    interactions: dict[int, dict[str, Any]] = {}
    for row in interactions_result.mappings().all():
        news_id = int(row["ai_news_id"])
        like_state = int(row.get("like_state") or 0)
        viewed = bool(row.get("viewed"))
        liked = like_state > 0
        skipped = like_state < 0 and not viewed
        interactions[news_id] = {
            "liked": liked,
            "saved": news_id in saved_ids,
            "viewed": viewed,
            "watch_time": int(row.get("watch_time") or 0),
            "like_count": 1 if liked else 0,
            "comment_count": comment_counts.get(news_id, 0),
            "topic_liked": liked,
            "skipped": skipped,
            "disliked": like_state < 0,
        }

    for news_id in unique_ids:
        interactions.setdefault(
            news_id,
            {
                "liked": False,
                "saved": news_id in saved_ids,
                "viewed": False,
                "watch_time": 0,
                "like_count": 0,
                "comment_count": comment_counts.get(news_id, 0),
                "topic_liked": False,
                "skipped": False,
                "disliked": False,
            },
        )

    return interactions
