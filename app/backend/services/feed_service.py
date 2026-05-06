"""
Feed Service Refactored - Clean Architecture

Orchestrator for feed generation pipeline.
Coordinates: loader -> ranker -> filter -> format

Key principles:
- Real-time generation (no stale precomputed feed)
- Fresh data only (48 hours)
- No raw_news fallback
- Correct interaction tracking (viewed != impression)
- Structured logging
"""

from typing import Any
from datetime import datetime, timedelta
import hashlib
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.core.logging import ContextLogger
from app.backend.db.sql_helpers import sql_timestamp_now
from app.backend.services.recommender_service import ensure_user_embedding
from app.backend.services.feed.feed_loader import (
    load_fresh_candidates,
    load_user_interactions,
)
from app.backend.services.feed.feed_ranker import (
    rank_items,
    separate_by_region,
)
from app.backend.services.feed.feed_filter import (
    filter_feed,
)

logger = ContextLogger(__name__)

DEFAULT_LIMIT = 50


async def _get_user_seen_ids(session: AsyncSession, user_id: int) -> set[int]:
    """
    Get set of ai_news_ids the user has VIEWED (not just seen in feed).
    
    viewed=True means user clicked/opened the article.
    This is different from just being in the feed.
    """
    cutoff = datetime.utcnow() - timedelta(days=30)
    query = """
    SELECT DISTINCT ai_news_id
    FROM interactions
    WHERE user_id = :user_id
      AND viewed = TRUE
      AND created_at >= :cutoff
    """
    
    result = await session.execute(
        text(query),
        {"user_id": user_id, "cutoff": cutoff}
    )
    
    seen_ids = {row[0] for row in result.fetchall()}
    logger.info("loaded_seen_ids", extra={"user_id": user_id, "count": len(seen_ids)})
    
    return seen_ids


async def _get_user_profile(session: AsyncSession, user_id: int) -> dict[str, Any] | None:
    """
    Load user profile for personalization.
    Returns None if user not found (no error).
    """
    query = """
    SELECT
        id,
        username,
        email,
        location,
        interests,
        country_code,
        region_code
    FROM users
    WHERE id = :user_id
    LIMIT 1
    """
    
    result = await session.execute(
        text(query),
        {"user_id": user_id}
    )
    
    row = result.mappings().first()
    return dict(row) if row else None


async def get_user_feed(
    session: AsyncSession,
    user_id: int,
    limit: int = DEFAULT_LIMIT,
) -> list[dict[str, Any]]:
    """
    Generate personalized feed for user.
    
    Pipeline:
    1. Load fresh candidates (ai_news, last 48h)
    2. Load user interactions (for optional enrichment)
    3. Load user seen items (for filtering)
    4. Rank candidates
    5. Filter (dedupe, remove seen, limit topics)
    6. Balance regional/global mix
    7. Format and return
    """
    
    limit = max(1, int(limit or DEFAULT_LIMIT))
    
    try:
        # Load user profile for context
        user_profile = await _get_user_profile(session, user_id)
        if not user_profile:
            logger.warning("user_not_found", extra={"user_id": user_id})
            return []
        
        # Step 1: Load fresh candidates
        candidates = await load_fresh_candidates(
            session,
            user_id,
            limit,
            freshness_hours=48
        )
        
        if not candidates:
            logger.warning("no_candidates", extra={"user_id": user_id})
            return []
        
        # Step 2: Load user interactions (optional enrichment)
        candidate_ids = [c.get("ai_news_id") for c in candidates]
        interactions = await load_user_interactions(session, user_id, candidate_ids)
        
        # Merge interactions into candidates
        for candidate in candidates:
            ai_news_id = candidate.get("ai_news_id")
            candidate["user_feed_id"] = int(ai_news_id or 0)
            candidate["user_id"] = user_id
            candidate["liked"] = False
            candidate["saved"] = False
            candidate["viewed"] = False
            candidate["is_viewed"] = False
            candidate["like_count"] = 0
            candidate["comment_count"] = 0
            if ai_news_id in interactions:
                interaction = interactions[ai_news_id]
                candidate.update({
                    "liked": bool(interaction.get("liked")),
                    "saved": bool(interaction.get("saved")),
                    "viewed": bool(interaction.get("viewed")),
                    "is_viewed": bool(interaction.get("viewed")),
                    "like_count": int(interaction.get("like_count") or 0),
                    "comment_count": int(interaction.get("comment_count") or 0),
                    "topic_liked": bool(interaction.get("topic_liked")),
                    "skipped": bool(interaction.get("skipped")),
                })
        
        # Step 3: Get seen items (for filtering)
        seen_ids = await _get_user_seen_ids(session, user_id)
        
        # Step 4: Detect cold start (Task 3: Cold start handling)
        interaction_cutoff = datetime.utcnow() - timedelta(days=30)
        interaction_count_query = """
        SELECT COUNT(*) as count
        FROM interactions
        WHERE user_id = :user_id
          AND created_at >= :cutoff
        """
        interaction_result = await session.execute(
            text(interaction_count_query),
            {"user_id": user_id, "cutoff": interaction_cutoff}
        )
        interaction_count = interaction_result.scalar() or 0
        is_cold_start = interaction_count < 5
        
        logger.info(
            "cold_start_detection",
            extra={"user_id": user_id, "interaction_count": interaction_count, "is_cold_start": is_cold_start}
        )
        
        # Rank items
        try:
            user_embedding = await ensure_user_embedding(session, user_id)
        except Exception as e:
            logger.warning("embedding_failed", extra={"error": str(e)})
            user_embedding = None
        
        ranked = rank_items(candidates, user_profile, user_embedding, is_cold_start=is_cold_start)
        
        # Step 5: Filter (Task 4: Quality threshold, Task 6: Failsafe)
        filtered = filter_feed(
            ranked,
            user_id,
            seen_ids=seen_ids,
            max_per_topic=3,
            min_score=0.0,
            allow_low_score_fallback=False
        )
        
        if not filtered:
            logger.warning("no_items_after_filter", extra={"user_id": user_id})
            return []
        
        # Step 6: Balance regional/global mix
        regional, global_news = separate_by_region(filtered)
        
        # Allocate slots: 60% regional, 40% global
        regional_limit = int(limit * 0.6)
        global_limit = int(limit * 0.4)
        
        final = regional[:regional_limit] + global_news[:global_limit]
        
        # Fill remaining slots if needed
        if len(final) < limit:
            used_ids = {item.get("ai_news_id") for item in final}
            leftovers = [
                item for item in filtered
                if item.get("ai_news_id") not in used_ids
            ]
            final.extend(leftovers[:max(0, limit - len(final))])
        
        final = final[:limit]

        def _valid_image_url(item: dict[str, Any]) -> bool:
            candidates: list[str] = []
            image_url = str(item.get("image_url") or "").strip()
            if image_url:
                candidates.append(image_url)

            urls = item.get("image_urls")
            if isinstance(urls, list):
                candidates.extend(str(value).strip() for value in urls if str(value).strip())

            if not candidates:
                return True

            for candidate in candidates:
                parsed = urlparse(candidate)
                if parsed.scheme in {"http", "https"} and bool(parsed.netloc):
                    return True
            return False

        seen_title_keys: set[str] = set()
        seen_content_hashes: set[str] = set()
        sanitized: list[dict[str, Any]] = []
        for item in final:
            title = str(item.get("final_title") or "").strip()
            text_value = str(item.get("final_text") or "").strip()
            if not title or not text_value:
                continue
            if not _valid_image_url(item):
                continue
            title_key = title.lower()
            content_hash = hashlib.sha256(f"{title_key}|{text_value.lower()}".encode("utf-8")).hexdigest()
            if title_key in seen_title_keys or content_hash in seen_content_hashes:
                continue
            seen_title_keys.add(title_key)
            seen_content_hashes.add(content_hash)
            sanitized.append(item)

        final = sanitized[:limit]
        
        # Step 7: Log metrics
        uz_language_count = sum(
            1 for item in final
            if str(item.get("language") or "").lower() == "uz"
        )
        uz_region_count = sum(
            1 for item in final
            if str(item.get("region") or "").lower() == "uz"
        )
        
        logger.info(
            "feed_generated",
            extra={
                "user_id": user_id,
                "candidates": len(candidates),
                "after_rank": len(ranked),
                "after_filter": len(filtered),
                "final": len(final),
                "uz_language": uz_language_count,
                "uz_region": uz_region_count,
            }
        )
        
        return final
        
    except Exception as e:
        logger.exception(
            "feed_generation_failed",
            extra={"user_id": user_id, "error": str(e)}
        )
        raise


async def create_comment(session: AsyncSession, user_id: int, ai_news_id: int, parent_comment_id: int | None, content: str) -> dict:
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented")


async def get_comments_tree(session: AsyncSession, user_id: int, ai_news_id: int) -> list[dict]:
    """Get comment tree for an article."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented")


async def record_interaction(session: AsyncSession, payload: dict) -> dict:
    """
    Record user interaction.
    
    IMPORTANT: This should track impressions separately from views.
    viewed=True should ONLY be set when user explicitly clicks/opens.
    """
    user_id = int(payload["user_id"])
    ai_news_id = int(payload["ai_news_id"])
    wants_like_toggle = payload.get("liked") is not None
    wants_view = bool(payload.get("viewed"))

    if ai_news_id <= 0:
        raise ValueError("ai_news_id must be > 0")

    if wants_like_toggle:
        now_sql = sql_timestamp_now(session)
        query = f"""
        INSERT INTO interactions (user_id, ai_news_id, liked, viewed, created_at)
        VALUES (:user_id, :ai_news_id, TRUE, FALSE, {now_sql})
        ON CONFLICT (user_id, ai_news_id)
        DO UPDATE SET
            liked = NOT COALESCE(interactions.liked, FALSE),
            created_at = {now_sql}
        RETURNING id, user_id, ai_news_id, liked, viewed, created_at
        """
    elif wants_view:
        now_sql = sql_timestamp_now(session)
        query = f"""
        INSERT INTO interactions (user_id, ai_news_id, liked, viewed, created_at)
        VALUES (:user_id, :ai_news_id, NULL, TRUE, {now_sql})
        ON CONFLICT (user_id, ai_news_id)
        DO UPDATE SET
            viewed = TRUE,
            created_at = {now_sql}
        RETURNING id, user_id, ai_news_id, liked, viewed, created_at
        """
    else:
        query = """
        SELECT id, user_id, ai_news_id, COALESCE(liked, FALSE) AS liked, viewed, created_at
        FROM interactions
        WHERE user_id = :user_id AND ai_news_id = :ai_news_id
        """

    if session.in_transaction():
        await session.commit()

    async with session.begin():
        result = await session.execute(
            text(query),
            {"user_id": user_id, "ai_news_id": ai_news_id},
        )
        row = result.mappings().first()

    if row is None:
        return {"liked": False}

    record = dict(row)
    record["liked"] = bool(record.get("liked"))

    if wants_like_toggle:
        logger.info(f"LIKE_TOGGLE user={user_id} news={ai_news_id} new_state={record['liked']}")

    return record


async def toggle_comment_like(session: AsyncSession, user_id: int, comment_id: int) -> dict:
    """Toggle like on a comment."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented")


async def toggle_saved_news(session: AsyncSession, user_id: int, ai_news_id: int) -> bool:
    """Toggle saved status of an article."""
    raise HTTPException(status_code=status.HTTP_501_NOT_IMPLEMENTED, detail="Not implemented")
