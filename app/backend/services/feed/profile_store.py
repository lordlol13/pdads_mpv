"""Lightweight in-memory user profile store for feed personalization.

Stores per-user counters for topics, sources and keywords.
Provides async helpers to get and update profile on interactions.

This is intentionally lightweight and kept in-memory to avoid DB schema changes.
It is updated on user interaction events and lazily populated from recent likes.
"""
from __future__ import annotations

import asyncio
import json
from collections import Counter
from datetime import datetime, timezone
from typing import Any

from app.backend.core.logging import ContextLogger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = ContextLogger(__name__)

# In-memory store: user_id -> profile dict
# profile structure: {"topics": {k: {"count": int, "last_seen": iso}}, "sources": {...}, "keywords": {...}}
_PROFILES: dict[int, dict[str, Any]] = {}
# Lock to protect concurrent updates
_LOCK = asyncio.Lock()


def _normalize_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
        except Exception:
            return datetime.now(timezone.utc)
    return datetime.now(timezone.utc)


async def _ensure_table(session: AsyncSession):
    try:
        await session.execute(text("CREATE TABLE IF NOT EXISTS user_profile (user_id integer PRIMARY KEY, data TEXT)") )
    except Exception:
        # ignore; table may be managed by migrations
        pass


async def _build_profile_from_db(session: AsyncSession, user_id: int) -> dict[str, Any]:
    """Build an initial profile snapshot from recent liked interactions.

    Aggregates recent liked interactions (90 days) into counts and last_seen timestamps.
    """
    try:
        query = text(
            """
            SELECT an.category AS category, rn.source_url AS source_url, an.final_text AS final_text, i.created_at AS created_at
            FROM interactions i
            JOIN ai_news an ON an.id = i.ai_news_id
            LEFT JOIN raw_news rn ON rn.id = an.raw_news_id
            WHERE i.user_id = :user_id
              AND COALESCE(i.liked, FALSE) = TRUE
              AND i.created_at >= (CURRENT_TIMESTAMP - INTERVAL '90 days')
            """
        )
        result = await session.execute(query, {"user_id": user_id})
        rows = result.mappings().all()

        topics = {}
        sources = {}
        keywords = {}

        for row in rows:
            created_at = _normalize_datetime(row.get("created_at"))

            cat = (row.get("category") or "").strip().lower()
            if cat:
                ent = topics.setdefault(cat, {"count": 0, "last_seen": None})
                ent["count"] += 1
                if not ent["last_seen"] or created_at > _normalize_datetime(ent["last_seen"]):
                    ent["last_seen"] = created_at.replace(tzinfo=timezone.utc).isoformat()

            src = (row.get("source_url") or "").strip().lower()
            if src:
                try:
                    from urllib.parse import urlparse
                    host = urlparse(src).hostname or src
                except Exception:
                    host = src
                ent = sources.setdefault(host, {"count": 0, "last_seen": None})
                ent["count"] += 1
                if not ent["last_seen"] or created_at > _normalize_datetime(ent["last_seen"]):
                    ent["last_seen"] = created_at.replace(tzinfo=timezone.utc).isoformat()

            text_val = (row.get("final_text") or "")
            for token in set(w.lower().strip(".,!?;:\"'()") for w in text_val.split() if len(w) > 3):
                ent = keywords.setdefault(token, {"count": 0, "last_seen": None})
                ent["count"] += 1
                if not ent["last_seen"] or created_at > _normalize_datetime(ent["last_seen"]):
                    ent["last_seen"] = created_at.replace(tzinfo=timezone.utc).isoformat()

        profile = {"topics": topics, "sources": sources, "keywords": keywords}
        return profile
    except Exception as exc:
        logger.warning("build_profile_failed", extra={"user_id": user_id, "error": str(exc)})
        return {"topics": {}, "sources": {}, "keywords": {}}


async def _read_profile_from_db(session: AsyncSession, user_id: int) -> dict[str, Any] | None:
    try:
        await _ensure_table(session)
        q = text("SELECT data FROM user_profile WHERE user_id = :user_id LIMIT 1")
        res = await session.execute(q, {"user_id": user_id})
        row = res.mappings().first()
        if not row:
            return None
        data = row.get("data")
        if isinstance(data, str):
            try:
                return json.loads(data)
            except Exception:
                return None
        return data
    except Exception:
        return None


async def _save_profile_to_db(session: AsyncSession, user_id: int, profile: dict[str, Any]):
    try:
        await _ensure_table(session)
        data_json = json.dumps(profile)
        q = text(
            "INSERT INTO user_profile (user_id, data) VALUES (:user_id, :data) "
            "ON CONFLICT (user_id) DO UPDATE SET data = EXCLUDED.data"
        )
        await session.execute(q, {"user_id": user_id, "data": data_json})
        try:
            await session.commit()
        except Exception:
            # commit may be handled by caller
            pass
    except Exception as exc:
        logger.warning("save_profile_failed", extra={"user_id": user_id, "error": str(exc)})


async def get_profile(session: AsyncSession | None, user_id: int) -> dict[str, Any]:
    """Return profile for user, attempting persisted profile first, otherwise build lazily."""
    async with _LOCK:
        if user_id in _PROFILES:
            return _PROFILES[user_id]

    profile = None
    if session is not None:
        profile = await _read_profile_from_db(session, user_id)

    if profile is None and session is not None:
        profile = await _build_profile_from_db(session, user_id)
        # persist built profile
        try:
            await _save_profile_to_db(session, user_id, profile)
        except Exception:
            pass

    profile = profile or {"topics": {}, "sources": {}, "keywords": {}}

    async with _LOCK:
        _PROFILES[user_id] = profile

    return profile


async def _update_counter_struct(struct: dict, key: str, delta: int):
    if not key:
        return
    ent = struct.setdefault(key, {"count": 0, "last_seen": None})
    ent["count"] = max(ent.get("count", 0) + delta, 0)
    ent["last_seen"] = datetime.now(timezone.utc).isoformat()


async def update_on_like(user_id: int, category: str | None, source_host: str | None, keywords: list[str] | None, session: AsyncSession | None = None):
    async with _LOCK:
        profile = _PROFILES.setdefault(user_id, {"topics": {}, "sources": {}, "keywords": {}})
        await _update_counter_struct(profile["topics"], (category or "").strip().lower(), 2)
        await _update_counter_struct(profile["sources"], (source_host or "").strip().lower(), 2)
        if keywords:
            for kw in keywords:
                await _update_counter_struct(profile["keywords"], kw.strip().lower(), 2)

    if session is not None:
        # persist
        try:
            await _save_profile_to_db(session, user_id, profile)
        except Exception:
            pass


async def update_on_view(user_id: int, category: str | None, source_host: str | None, keywords: list[str] | None, session: AsyncSession | None = None):
    async with _LOCK:
        profile = _PROFILES.setdefault(user_id, {"topics": {}, "sources": {}, "keywords": {}})
        await _update_counter_struct(profile["topics"], (category or "").strip().lower(), 1)
        await _update_counter_struct(profile["sources"], (source_host or "").strip().lower(), 1)
        if keywords:
            for kw in keywords:
                await _update_counter_struct(profile["keywords"], kw.strip().lower(), 1)

    if session is not None:
        try:
            await _save_profile_to_db(session, user_id, profile)
        except Exception:
            pass


async def update_on_skip(user_id: int, category: str | None, source_host: str | None, keywords: list[str] | None, session: AsyncSession | None = None):
    async with _LOCK:
        profile = _PROFILES.setdefault(user_id, {"topics": {}, "sources": {}, "keywords": {}})
        # reduce count but keep floor at 0
        await _update_counter_struct(profile["topics"], (category or "").strip().lower(), -1)
        await _update_counter_struct(profile["sources"], (source_host or "").strip().lower(), -1)
        if keywords:
            for kw in keywords:
                await _update_counter_struct(profile["keywords"], kw.strip().lower(), -1)

    if session is not None:
        try:
            await _save_profile_to_db(session, user_id, profile)
        except Exception:
            pass


def extract_keywords_from_text(text: str, max_tokens: int = 6) -> list[str]:
    if not text:
        return []
    words = [w.lower().strip(".,!?;:\"'()") for w in text.split() if len(w) > 3]
    # simple frequency
    freq = Counter(words)
    return [k for k, _ in freq.most_common(max_tokens)]
