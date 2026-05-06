"""
Interaction Tracking Module

Clarifies the difference between:
- IMPRESSION: User sees item in feed
- VIEW: User clicks/opens item detail

This is critical for correct ranking model.
"""

from typing import Any
from datetime import datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.core.logging import ContextLogger
from app.backend.db.sql_helpers import sql_timestamp_now

logger = ContextLogger(__name__)


async def record_impression(
    session: AsyncSession,
    user_id: int,
    ai_news_id: int,
    position: int = 0,
) -> dict[str, Any]:
    """
    Record that user SAW item in feed.
    
    impression = item appeared in user's feed
    
    Do NOT set viewed=True here.
    """
    now_sql = sql_timestamp_now(session)
    query = f"""
    INSERT INTO user_events (user_id, ai_news_id, event_type, position, created_at)
    VALUES (:user_id, :ai_news_id, 'impression', :position, {now_sql})
    ON CONFLICT (user_id, ai_news_id, event_type, DATE(created_at))
    DO UPDATE SET position = EXCLUDED.position
    RETURNING id, event_type, created_at
    """
    
    result = await session.execute(
        text(query),
        {
            "user_id": user_id,
            "ai_news_id": ai_news_id,
            "position": position,
        }
    )
    
    await session.commit()
    row = result.mappings().first()
    
    logger.info(
        "impression_recorded",
        extra={
            "user_id": user_id,
            "ai_news_id": ai_news_id,
            "position": position,
        }
    )
    
    return dict(row) if row else {}


async def record_view(
    session: AsyncSession,
    user_id: int,
    ai_news_id: int,
    dwell_time_seconds: int | None = None,
) -> dict[str, Any]:
    """
    Record that user CLICKED/OPENED item.
    
    view = user explicitly opened article detail
    
    This is when viewed=True is set.
    """
    now_sql = sql_timestamp_now(session)
    query = f"""
    INSERT INTO user_feed (user_id, ai_news_id, viewed, dwell_time, created_at)
    VALUES (:user_id, :ai_news_id, TRUE, :dwell_time, {now_sql})
    ON CONFLICT (user_id, ai_news_id) 
    DO UPDATE SET viewed = TRUE, dwell_time = COALESCE(:dwell_time, user_feed.dwell_time)
    RETURNING id, user_id, ai_news_id, viewed, dwell_time, created_at
    """
    
    result = await session.execute(
        text(query),
        {
            "user_id": user_id,
            "ai_news_id": ai_news_id,
            "dwell_time": dwell_time_seconds,
        }
    )
    
    await session.commit()
    row = result.mappings().first()
    
    logger.info(
        "view_recorded",
        extra={
            "user_id": user_id,
            "ai_news_id": ai_news_id,
            "dwell_time": dwell_time_seconds,
        }
    )
    
    return dict(row) if row else {}


async def record_like(
    session: AsyncSession,
    user_id: int,
    ai_news_id: int,
    is_liked: bool = True,
) -> dict[str, Any]:
    """
    Record like/unlike on article.
    """
    now_sql = sql_timestamp_now(session)
    query = f"""
    INSERT INTO user_feed (user_id, ai_news_id, liked, created_at)
    VALUES (:user_id, :ai_news_id, :is_liked, {now_sql})
    ON CONFLICT (user_id, ai_news_id) 
    DO UPDATE SET liked = :is_liked
    RETURNING id, user_id, ai_news_id, liked, like_count, created_at
    """
    
    result = await session.execute(
        text(query),
        {
            "user_id": user_id,
            "ai_news_id": ai_news_id,
            "is_liked": is_liked,
        }
    )
    
    await session.commit()
    row = result.mappings().first()
    
    logger.info(
        "like_recorded",
        extra={
            "user_id": user_id,
            "ai_news_id": ai_news_id,
            "is_liked": is_liked,
        }
    )
    
    return dict(row) if row else {}


async def record_save(
    session: AsyncSession,
    user_id: int,
    ai_news_id: int,
    is_saved: bool = True,
) -> dict[str, Any]:
    """
    Record save/unsave on article.
    """
    now_sql = sql_timestamp_now(session)
    query = f"""
    INSERT INTO user_feed (user_id, ai_news_id, saved, created_at)
    VALUES (:user_id, :ai_news_id, :is_saved, {now_sql})
    ON CONFLICT (user_id, ai_news_id) 
    DO UPDATE SET saved = :is_saved
    RETURNING id, user_id, ai_news_id, saved, created_at
    """
    
    result = await session.execute(
        text(query),
        {
            "user_id": user_id,
            "ai_news_id": ai_news_id,
            "is_saved": is_saved,
        }
    )
    
    await session.commit()
    row = result.mappings().first()
    
    logger.info(
        "save_recorded",
        extra={
            "user_id": user_id,
            "ai_news_id": ai_news_id,
            "is_saved": is_saved,
        }
    )
    
    return dict(row) if row else {}


async def record_skip(
    session: AsyncSession,
    user_id: int,
    ai_news_id: int,
) -> dict[str, Any]:
    """
    Record user skip/dismiss of article.
    
    Negative engagement signal.
    """
    now_sql = sql_timestamp_now(session)
    query = f"""
    INSERT INTO user_events (user_id, ai_news_id, event_type, created_at)
    VALUES (:user_id, :ai_news_id, 'skip', {now_sql})
    ON CONFLICT (user_id, ai_news_id, event_type, DATE(created_at))
    DO UPDATE SET event_type = EXCLUDED.event_type
    RETURNING id, event_type, created_at
    """
    
    result = await session.execute(
        text(query),
        {
            "user_id": user_id,
            "ai_news_id": ai_news_id,
        }
    )
    
    await session.commit()
    row = result.mappings().first()
    
    logger.info(
        "skip_recorded",
        extra={
            "user_id": user_id,
            "ai_news_id": ai_news_id,
        }
    )
    
    return dict(row) if row else {}


# Event type enum
class EventType:
    """Event types for user interactions."""
    IMPRESSION = "impression"  # Saw in feed
    VIEW = "view"              # Clicked/opened
    LIKE = "like"              # Liked
    SAVE = "save"              # Saved
    SKIP = "skip"              # Dismissed
    LONG_VIEW = "long_view"    # Dwell time > 10s
