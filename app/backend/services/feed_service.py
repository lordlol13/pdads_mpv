import json
import re
from hashlib import sha256
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.db.sql_helpers import sql_timestamp_now
from app.backend.services.recommender_service import rank_feed_rows, refresh_user_embedding, ensure_user_embedding
from app.backend.services.media_service import canonical_image_key


_SOCIAL_TABLES_READY_DIALECTS: set[str] = set()


def _normalize_topics(values: list[str]) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip().lower()
        if not item or item in seen:
            continue
        seen.add(item)
        normalized.append(item)
    return normalized


def _extract_user_topics(raw_interests: Any) -> list[str]:
    payload: dict[str, Any] = {}
    if isinstance(raw_interests, dict):
        payload = raw_interests
    elif isinstance(raw_interests, str) and raw_interests.strip():
        try:
            parsed = json.loads(raw_interests)
            if isinstance(parsed, dict):
                payload = parsed
        except json.JSONDecodeError:
            payload = {}

    values: list[str] = []
    for key in ("all_topics", "topics", "custom_topics"):
        raw_list = payload.get(key)
        if isinstance(raw_list, list):
            values.extend([str(item).strip().lower() for item in raw_list if str(item).strip()])

    return _normalize_topics(values)


def _persona_matches_topics(target_persona: str | None, topics: list[str]) -> bool:
    normalized_topics = _normalize_topics(topics)
    if not normalized_topics:
        return True

    persona = str(target_persona or "").strip().lower()
    if not persona:
        return False

    for normalized in normalized_topics:
        if normalized == "general":
            if persona == "general" or persona.startswith("general|"):
                return True
            continue
        if persona == normalized or persona.startswith(f"{normalized}|"):
            return True

    return False


def _normalize_title_key(value: str | None) -> str:
    title = str(value or "").strip().lower()
    if not title:
        return ""
    return re.sub(r"\s+", " ", title)


def _normalize_text_key(value: str | None) -> str:
    if not value:
        return ""
    raw = str(value or "")
    # lower, remove punctuation, collapse whitespace
    cleaned = re.sub(r"[^\w\s]", "", raw.lower())
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned[:1000]


def _dedupe_feed_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    if not rows:
        return []

    kept_rows: list[dict[str, Any]] = []
    sig_to_idx: dict[str, int] = {}
    idx_to_sigs: dict[int, set[str]] = {}

    def _make_signatures(row: dict[str, Any]) -> list[str]:
        sigs: list[str] = []
        raw_news_id = int(row.get("raw_news_id") or 0)
        if raw_news_id > 0:
            sigs.append(f"raw:{raw_news_id}")

        title_key = _normalize_title_key(row.get("final_title"))
        if title_key:
            sigs.append(f"title:{title_key}")

        text_norm = _normalize_text_key(row.get("final_text"))
        if text_norm:
            text_hash = sha256(text_norm[:500].encode("utf-8")).hexdigest()[:16]
            sigs.append(f"text:{text_hash}")

        image_urls = row.get("image_urls")
        first_image = None
        if isinstance(image_urls, list) and image_urls:
            first_image = image_urls[0]
        elif isinstance(image_urls, str) and image_urls.strip():
            try:
                parsed = json.loads(image_urls)
                if isinstance(parsed, list) and parsed:
                    first_image = parsed[0]
                else:
                    first_image = image_urls.strip()
            except Exception:
                first_image = image_urls.strip()

        if first_image:
            img_key = canonical_image_key(first_image)
            if img_key:
                sigs.append(f"img:{img_key}")

        # Fallback to ai_news id
        ai_news_id = int(row.get("ai_news_id") or 0)
        if not sigs:
            sigs.append(f"ai:{ai_news_id}")
        return sigs

    for row in rows:
        sigs = _make_signatures(row)
        collisions = {sig_to_idx[s] for s in sigs if s in sig_to_idx}

        if not collisions:
            idx = len(kept_rows)
            kept_rows.append(row)
            idx_to_sigs[idx] = set(sigs)
            for s in sigs:
                sig_to_idx[s] = idx
            continue

        # For simplicity, compare to the first colliding kept row.
        existing_idx = next(iter(collisions))
        existing = kept_rows[existing_idx]

        current_rank = float(row.get("rank_score") or 0.0)
        existing_rank = float(existing.get("rank_score") or 0.0)
        current_saved = bool(row.get("saved"))
        existing_saved = bool(existing.get("saved"))
        current_ai_score = float(row.get("ai_score") or 0.0)
        existing_ai_score = float(existing.get("ai_score") or 0.0)
        current_feed_id = int(row.get("user_feed_id") or 0)
        existing_feed_id = int(existing.get("user_feed_id") or 0)

        should_replace = (
            (current_saved and not existing_saved)
            or (current_saved == existing_saved and current_rank > existing_rank)
            or (
                current_saved == existing_saved
                and abs(current_rank - existing_rank) < 1e-9
                and current_ai_score > existing_ai_score
            )
            or (
                current_saved == existing_saved
                and abs(current_rank - existing_rank) < 1e-9
                and abs(current_ai_score - existing_ai_score) < 1e-9
                and current_feed_id > existing_feed_id
            )
        )

        if should_replace:
            # remove old signatures
            for s in idx_to_sigs.get(existing_idx, set()):
                sig_to_idx.pop(s, None)

            # replace row in place
            kept_rows[existing_idx] = row
            idx_to_sigs[existing_idx] = set(sigs)
            for s in sigs:
                sig_to_idx[s] = existing_idx
        # else: skip adding this row (inferior duplicate)

    deduped = list(kept_rows)
    deduped.sort(
        key=lambda item: (
            bool(item.get("saved")),
            float(item.get("rank_score") or 0.0),
            int(item.get("user_feed_id") or 0),
        ),
        reverse=True,
    )
    return deduped[:limit]


async def _backfill_user_feed_if_empty(session: AsyncSession, *, user_id: int, user_topics: list[str]) -> int:
    existing = await session.execute(
        text(
            """
            SELECT 1
            FROM user_feed
            WHERE user_id = :user_id
            LIMIT 1
            """
        ),
        {"user_id": user_id},
    )
    if existing.scalar_one_or_none() is not None:
        return 0

    candidates_result = await session.execute(
        text(
            """
            SELECT id, ai_score, target_persona, raw_news_id
            FROM ai_news
            ORDER BY created_at DESC, id DESC
            LIMIT 400
            """
        )
    )
    candidates = [dict(row) for row in candidates_result.mappings().all()]
    if not candidates:
        return 0

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    selected_raw_news_ids: set[int] = set()

    normalized_topics = _normalize_topics(user_topics)
    if normalized_topics:
        for row in candidates:
            ai_news_id = int(row.get("id") or 0)
            if not ai_news_id or ai_news_id in selected_ids:
                continue

            raw_news_id = int(row.get("raw_news_id") or 0)
            if raw_news_id and raw_news_id in selected_raw_news_ids:
                continue

            persona = str(row.get("target_persona") or "").strip().lower()
            if not _persona_matches_topics(persona, normalized_topics):
                continue

            selected_ids.add(ai_news_id)
            if raw_news_id:
                selected_raw_news_ids.add(raw_news_id)
            selected.append({"ai_news_id": ai_news_id, "ai_score": float(row.get("ai_score") or 0.0)})
            if len(selected) >= 40:
                break

    if not selected:
        for row in candidates:
            ai_news_id = int(row.get("id") or 0)
            if not ai_news_id or ai_news_id in selected_ids:
                continue

            raw_news_id = int(row.get("raw_news_id") or 0)
            if raw_news_id and raw_news_id in selected_raw_news_ids:
                continue

            selected_ids.add(ai_news_id)
            if raw_news_id:
                selected_raw_news_ids.add(raw_news_id)
            selected.append({"ai_news_id": ai_news_id, "ai_score": float(row.get("ai_score") or 0.0)})
            if len(selected) >= 20:
                break

    if not selected:
        return 0

    now_sql = sql_timestamp_now(session)
    inserted = 0
    for item in selected:
        result = await session.execute(
            text(
                f"""
                INSERT INTO user_feed (user_id, ai_news_id, ai_score, created_at)
                SELECT :user_id, :ai_news_id, :ai_score, {now_sql}
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM user_feed uf
                    WHERE uf.user_id = :user_id
                      AND uf.ai_news_id = :ai_news_id
                )
                """
            ),
            {
                "user_id": user_id,
                "ai_news_id": item["ai_news_id"],
                "ai_score": item["ai_score"],
            },
        )
        inserted += int(getattr(result, "rowcount", 0) or 0)

    if inserted > 0:
        await session.commit()

    return inserted


async def _top_up_user_feed(session: AsyncSession, *, user_id: int, user_topics: list[str], needed: int) -> int:
    """Insert up to `needed` additional ai_news into `user_feed` for the given user.

    Uses recent `ai_news` rows not yet present in `user_feed` and matching the
    user's topics. Returns number of rows inserted.
    """
    if needed <= 0:
        return 0

    # load recent candidates not already in user's feed
    candidates_result = await session.execute(
        text(
            """
            SELECT id, ai_score, target_persona, raw_news_id
            FROM ai_news
            WHERE id NOT IN (SELECT ai_news_id FROM user_feed WHERE user_id = :user_id)
            ORDER BY created_at DESC, id DESC
            LIMIT 400
            """
        ),
        {"user_id": user_id},
    )
    candidates = [dict(row) for row in candidates_result.mappings().all()]
    if not candidates:
        return 0

    selected: list[dict[str, Any]] = []
    selected_ids: set[int] = set()
    selected_raw_news_ids: set[int] = set()

    normalized_topics = _normalize_topics(user_topics)
    if normalized_topics:
        for row in candidates:
            ai_news_id = int(row.get("id") or 0)
            if not ai_news_id or ai_news_id in selected_ids:
                continue

            raw_news_id = int(row.get("raw_news_id") or 0)
            if raw_news_id and raw_news_id in selected_raw_news_ids:
                continue

            persona = str(row.get("target_persona") or "").strip().lower()
            if not _persona_matches_topics(persona, normalized_topics):
                continue

            selected_ids.add(ai_news_id)
            if raw_news_id:
                selected_raw_news_ids.add(raw_news_id)
            selected.append({"ai_news_id": ai_news_id, "ai_score": float(row.get("ai_score") or 0.0)})
            if len(selected) >= needed:
                break

    if len(selected) < needed:
        for row in candidates:
            ai_news_id = int(row.get("id") or 0)
            if not ai_news_id or ai_news_id in selected_ids:
                continue

            raw_news_id = int(row.get("raw_news_id") or 0)
            if raw_news_id and raw_news_id in selected_raw_news_ids:
                continue

            selected_ids.add(ai_news_id)
            if raw_news_id:
                selected_raw_news_ids.add(raw_news_id)
            selected.append({"ai_news_id": ai_news_id, "ai_score": float(row.get("ai_score") or 0.0)})
            if len(selected) >= needed:
                break

    if not selected:
        return 0

    now_sql = sql_timestamp_now(session)
    inserted = 0
    for item in selected[:needed]:
        result = await session.execute(
            text(
                f"""
                INSERT INTO user_feed (user_id, ai_news_id, ai_score, created_at)
                SELECT :user_id, :ai_news_id, :ai_score, {now_sql}
                WHERE NOT EXISTS (
                    SELECT 1
                    FROM user_feed uf
                    WHERE uf.user_id = :user_id
                      AND uf.ai_news_id = :ai_news_id
                )
                """
            ),
            {
                "user_id": user_id,
                "ai_news_id": item["ai_news_id"],
                "ai_score": item["ai_score"],
            },
        )
        inserted += int(getattr(result, "rowcount", 0) or 0)

    if inserted > 0:
        await session.commit()

    return inserted


async def _ensure_social_tables(session: AsyncSession) -> None:
    dialect = session.get_bind().dialect.name
    if dialect in _SOCIAL_TABLES_READY_DIALECTS:
        return

    if dialect == "sqlite":
        statements = [
            """
            CREATE TABLE IF NOT EXISTS saved_news (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ai_news_id INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, ai_news_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_saved_news_user_created
            ON saved_news(user_id, created_at DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS feed_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ai_news_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                parent_comment_id INTEGER NULL,
                content TEXT NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_feed_comments_ai_news_created
            ON feed_comments(ai_news_id, created_at ASC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_feed_comments_parent
            ON feed_comments(parent_comment_id)
            """,
            """
            CREATE TABLE IF NOT EXISTS feed_comment_likes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                comment_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(comment_id, user_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_feed_comment_likes_comment
            ON feed_comment_likes(comment_id)
            """,
        ]
    else:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS saved_news (
                id BIGSERIAL PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                ai_news_id INTEGER NOT NULL REFERENCES ai_news(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(user_id, ai_news_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_saved_news_user_created
            ON saved_news(user_id, created_at DESC)
            """,
            """
            CREATE TABLE IF NOT EXISTS feed_comments (
                id BIGSERIAL PRIMARY KEY,
                ai_news_id INTEGER NOT NULL REFERENCES ai_news(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                parent_comment_id BIGINT NULL REFERENCES feed_comments(id) ON DELETE CASCADE,
                content TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_feed_comments_ai_news_created
            ON feed_comments(ai_news_id, created_at ASC)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_feed_comments_parent
            ON feed_comments(parent_comment_id)
            """,
            """
            CREATE TABLE IF NOT EXISTS feed_comment_likes (
                id BIGSERIAL PRIMARY KEY,
                comment_id BIGINT NOT NULL REFERENCES feed_comments(id) ON DELETE CASCADE,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                UNIQUE(comment_id, user_id)
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_feed_comment_likes_comment
            ON feed_comment_likes(comment_id)
            """,
        ]

    for statement in statements:
        await session.execute(text(statement))

    await session.commit()
    _SOCIAL_TABLES_READY_DIALECTS.add(dialect)


async def _log_feed_impressions(session: AsyncSession, *, user_id: int, rows: list[dict[str, Any]]) -> None:
    """Persist served feed positions for CTR/accuracy analytics."""
    if not rows:
        return

    now_sql = sql_timestamp_now(session)
    for index, row in enumerate(rows, start=1):
        ai_news_id = int(row.get("ai_news_id") or 0)
        if ai_news_id <= 0:
            continue
        await session.execute(
            text(
                f"""
                INSERT INTO feed_feature_log (user_id, ai_news_id, reason, feature_value, rank_position, created_at)
                VALUES (:user_id, :ai_news_id, :reason, :feature_value, :rank_position, {now_sql})
                """
            ),
            {
                "user_id": user_id,
                "ai_news_id": ai_news_id,
                "reason": "feed_served",
                "feature_value": float(row.get("rank_score") or 0.0),
                "rank_position": index,
            },
        )

        # Record an impression as a 'viewed' interaction so the same item is not re-served to the user
        try:
            await session.execute(
                text(
                    f"""
                    INSERT INTO interactions (user_id, ai_news_id, liked, viewed, watch_time, created_at)
                    SELECT :user_id, :ai_news_id, NULL, TRUE, NULL, {now_sql}
                    WHERE NOT EXISTS (
                        SELECT 1 FROM interactions i
                        WHERE i.user_id = :user_id
                          AND i.ai_news_id = :ai_news_id
                          AND COALESCE(i.viewed, FALSE) = TRUE
                    )
                    """
                ),
                {
                    "user_id": user_id,
                    "ai_news_id": ai_news_id,
                },
            )
        except Exception:
            # Silently ignore impression->interaction failures to avoid breaking feed serving
            pass

    await session.commit()


async def get_user_feed(session: AsyncSession, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    await _ensure_social_tables(session)
    query_limit = max(int(limit or 0), 1) * 6

    user_interests_result = await session.execute(
        text(
            """
            SELECT interests
            FROM users
            WHERE id = :user_id
            LIMIT 1
            """
        ),
        {"user_id": user_id},
    )
    raw_interests = user_interests_result.scalar_one_or_none()
    user_topics = _extract_user_topics(raw_interests)

    query = """
    WITH dedup_user_feed AS (
        SELECT
            uf.id,
            uf.user_id,
            uf.ai_news_id,
            uf.ai_score,
            uf.created_at,
            ROW_NUMBER() OVER (
                PARTITION BY uf.user_id, uf.ai_news_id
                ORDER BY uf.created_at DESC, uf.id DESC
            ) AS rn
        FROM user_feed uf
        WHERE uf.user_id = :user_id
    ),
    latest_interactions AS (
        SELECT
            i.user_id,
            i.ai_news_id,
            i.liked,
            i.viewed,
            ROW_NUMBER() OVER (
                PARTITION BY i.user_id, i.ai_news_id
                ORDER BY i.created_at DESC, i.id DESC
            ) AS rn
        FROM interactions i
        WHERE i.user_id = :user_id
    ),
    persona_feedback AS (
        SELECT
            an.target_persona,
            SUM(
                CASE
                    WHEN li.liked = TRUE THEN 1
                    WHEN li.liked = FALSE THEN -1
                    ELSE 0
                END
            ) AS persona_score
        FROM latest_interactions li
        JOIN ai_news an ON an.id = li.ai_news_id
        WHERE li.rn = 1
        GROUP BY an.target_persona
    ),
    comment_counts AS (
        SELECT
            c.ai_news_id,
            COUNT(*) AS comment_count
        FROM feed_comments c
        GROUP BY c.ai_news_id
    ),
    latest_interactions_global AS (
        SELECT
            i.user_id,
            i.ai_news_id,
            i.liked,
            ROW_NUMBER() OVER (
                PARTITION BY i.user_id, i.ai_news_id
                ORDER BY i.created_at DESC, i.id DESC
            ) AS rn
        FROM interactions i
    ),
    like_counts AS (
        SELECT
            ai_news_id,
            COUNT(*) FILTER (WHERE liked = TRUE) AS like_count
        FROM latest_interactions_global
        WHERE rn = 1
        GROUP BY ai_news_id
    )
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
        an.image_urls,
        an.video_urls,
        an.category,
        an.embedding_vector,
        an.vector_status,
        li.liked,
        COALESCE(lc.like_count, 0) AS like_count,
        CASE
            WHEN sn.id IS NULL THEN FALSE
            ELSE TRUE
        END AS saved,
        COALESCE(cc.comment_count, 0) AS comment_count,
        (
            COALESCE(uf.ai_score, 0)
            + COALESCE(pf.persona_score, 0) * 0.75
            + CASE
                WHEN li.liked = TRUE THEN 2
                WHEN li.liked = FALSE THEN -2
                ELSE 0
              END
        ) AS rank_score
    FROM user_feed uf
    JOIN dedup_user_feed duf
        ON duf.id = uf.id
        AND duf.rn = 1
    JOIN ai_news an ON an.id = uf.ai_news_id
    LEFT JOIN latest_interactions li
        ON li.user_id = uf.user_id
        AND li.ai_news_id = uf.ai_news_id
        AND li.rn = 1
    LEFT JOIN persona_feedback pf
        ON pf.target_persona = an.target_persona
    LEFT JOIN saved_news sn
        ON sn.user_id = uf.user_id
        AND sn.ai_news_id = uf.ai_news_id
    LEFT JOIN comment_counts cc
        ON cc.ai_news_id = uf.ai_news_id
    LEFT JOIN like_counts lc
        ON lc.ai_news_id = uf.ai_news_id
    WHERE uf.user_id = :user_id
        AND (
            :exclude_viewed = FALSE
            OR NOT (COALESCE(li.viewed, FALSE) = TRUE AND sn.id IS NULL)
        )
    ORDER BY rank_score DESC, uf.id DESC
    LIMIT :query_limit
    """
    async def _load_rows(exclude_viewed: bool) -> list[dict[str, Any]]:
        result = await session.execute(
            text(query),
            {
                "user_id": user_id,
                "query_limit": query_limit,
                "exclude_viewed": exclude_viewed,
            },
        )
        return [dict(row) for row in result.mappings().all()]

    rows = await _load_rows(True)
    if not rows:
        inserted = await _backfill_user_feed_if_empty(session, user_id=user_id, user_topics=user_topics)
        if inserted > 0:
            rows = await _load_rows(True)

    # If the user's feed is running low, try to top-up from existing `ai_news`.
    try:
        current_count = len(rows or [])
        if current_count < int(limit or 50):
            needed = int(limit or 50) - current_count
            if needed > 0:
                try:
                    added = await _top_up_user_feed(session, user_id=user_id, user_topics=user_topics, needed=needed)
                    if added > 0:
                        rows = await _load_rows(True)
                except Exception:
                    # don't let top-up failures break feed serving
                    pass

            # If we still have few items, enqueue scheduled ingestion to generate more items
            if (len(rows or []) < int(limit or 50)):
                try:
                    # import the celery task lazily to avoid import cycles
                    from brain.tasks.pipeline_tasks import scheduled_ingestion as _scheduled_ingestion_task
                    # schedule background ingestion to replenish ai_news/user_feed
                    try:
                        _scheduled_ingestion_task.delay()
                    except Exception:
                        # If delay fails (no celery), ignore
                        pass
                except Exception:
                    # If task import fails, ignore
                    pass
    except Exception:
        # If any unexpected error occurred during top-up or scheduling, ignore
        # to avoid breaking feed serving.
        pass

    # Safety fallback: do not return empty feed solely because all items were marked viewed.
    if not rows:
        rows = await _load_rows(False)

    user_embedding = await ensure_user_embedding(session, user_id)

    if user_topics:
        filtered: list[dict[str, Any]] = []
        for row in rows:
            if bool(row.get("saved")):
                filtered.append(row)
                continue
            if _persona_matches_topics(row.get("target_persona"), user_topics):
                filtered.append(row)

        if filtered:
            rows = filtered

    ranked_rows = rank_feed_rows(rows, user_embedding=user_embedding, limit=limit, user_topics=user_topics)
    deduped_rows = _dedupe_feed_rows(ranked_rows, limit)

    try:
        await _log_feed_impressions(session, user_id=user_id, rows=deduped_rows)
    except Exception:
        # Metrics logging must not break feed serving.
        await session.rollback()

    return deduped_rows


async def record_interaction(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    await _ensure_social_tables(session)

    now_sql = sql_timestamp_now(session)
    query = f"""
    INSERT INTO interactions (
        user_id, ai_news_id, liked, viewed, watch_time, created_at
    )
    VALUES (
        :user_id, :ai_news_id, :liked, :viewed, :watch_time, {now_sql}
    )
    RETURNING id, user_id, ai_news_id, liked, viewed, watch_time, created_at
    """
    result = await session.execute(text(query), payload)
    await session.commit()
    row = result.mappings().first()
    user_id = int(payload.get("user_id") or 0)
    if user_id > 0:
        try:
            await refresh_user_embedding(session, user_id)
        except Exception:
            pass
    return dict(row) if row is not None else {"id": -1, "status": "created"}


async def toggle_saved_news(session: AsyncSession, user_id: int, ai_news_id: int) -> bool:
    await _ensure_social_tables(session)

    existing = await session.execute(
        text(
            """
            SELECT id
            FROM saved_news
            WHERE user_id = :user_id AND ai_news_id = :ai_news_id
            LIMIT 1
            """
        ),
        {"user_id": user_id, "ai_news_id": ai_news_id},
    )
    existing_id = existing.scalar_one_or_none()

    if existing_id is not None:
        await session.execute(
            text("DELETE FROM saved_news WHERE id = :id"),
            {"id": existing_id},
        )
        await session.commit()
        try:
            await refresh_user_embedding(session, user_id)
        except Exception:
            pass
        return False

    now_sql = sql_timestamp_now(session)
    await session.execute(
        text(
            f"""
            INSERT INTO saved_news (user_id, ai_news_id, created_at)
            VALUES (:user_id, :ai_news_id, {now_sql})
            """
        ),
        {"user_id": user_id, "ai_news_id": ai_news_id},
    )
    await session.commit()
    try:
        await refresh_user_embedding(session, user_id)
    except Exception:
        pass
    return True


async def create_comment(
    session: AsyncSession,
    *,
    user_id: int,
    ai_news_id: int,
    parent_comment_id: int | None,
    content: str,
) -> dict[str, Any]:
    await _ensure_social_tables(session)

    ai_news_row = await session.execute(
        text("SELECT id FROM ai_news WHERE id = :ai_news_id LIMIT 1"),
        {"ai_news_id": ai_news_id},
    )
    if ai_news_row.scalar_one_or_none() is None:
        raise ValueError("ai_news_not_found")

    if parent_comment_id is not None:
        parent_row = await session.execute(
            text(
                """
                SELECT id
                FROM feed_comments
                WHERE id = :parent_comment_id AND ai_news_id = :ai_news_id
                LIMIT 1
                """
            ),
            {"parent_comment_id": parent_comment_id, "ai_news_id": ai_news_id},
        )
        if parent_row.scalar_one_or_none() is None:
            raise ValueError("parent_comment_not_found")

    now_sql = sql_timestamp_now(session)
    insert_result = await session.execute(
        text(
            f"""
            INSERT INTO feed_comments (ai_news_id, user_id, parent_comment_id, content, created_at)
            VALUES (:ai_news_id, :user_id, :parent_comment_id, :content, {now_sql})
            RETURNING id
            """
        ),
        {
            "ai_news_id": ai_news_id,
            "user_id": user_id,
            "parent_comment_id": parent_comment_id,
            "content": content.strip(),
        },
    )
    comment_id = int(insert_result.scalar_one())
    await session.commit()

    created = await session.execute(
        text(
            """
            SELECT
                c.id,
                c.ai_news_id,
                c.user_id,
                u.username,
                c.parent_comment_id,
                c.content,
                c.created_at,
                0 AS like_count,
                FALSE AS liked_by_me
            FROM feed_comments c
            JOIN users u ON u.id = c.user_id
            WHERE c.id = :comment_id
            LIMIT 1
            """
        ),
        {"comment_id": comment_id},
    )
    row = created.mappings().first()
    return dict(row) if row else {}


async def get_comments_tree(session: AsyncSession, *, user_id: int, ai_news_id: int) -> list[dict[str, Any]]:
    await _ensure_social_tables(session)

    query = """
    SELECT
        c.id,
        c.ai_news_id,
        c.user_id,
        u.username,
        c.parent_comment_id,
        c.content,
        c.created_at,
        COALESCE(like_stats.like_count, 0) AS like_count,
        CASE
            WHEN my_like.id IS NULL THEN FALSE
            ELSE TRUE
        END AS liked_by_me
    FROM feed_comments c
    JOIN users u ON u.id = c.user_id
    LEFT JOIN (
        SELECT
            comment_id,
            COUNT(*) AS like_count
        FROM feed_comment_likes
        GROUP BY comment_id
    ) like_stats ON like_stats.comment_id = c.id
    LEFT JOIN feed_comment_likes my_like
        ON my_like.comment_id = c.id
        AND my_like.user_id = :user_id
    WHERE c.ai_news_id = :ai_news_id
    ORDER BY c.created_at ASC, c.id ASC
    """
    result = await session.execute(text(query), {"user_id": user_id, "ai_news_id": ai_news_id})
    rows = [dict(row) for row in result.mappings().all()]

    by_id: dict[int, dict[str, Any]] = {}
    roots: list[dict[str, Any]] = []

    for row in rows:
        row["replies"] = []
        by_id[int(row["id"])] = row

    for row in rows:
        parent_id = row.get("parent_comment_id")
        if parent_id is None:
            roots.append(row)
            continue
        parent = by_id.get(int(parent_id))
        if parent is None:
            roots.append(row)
            continue
        parent.setdefault("replies", []).append(row)

    return roots


async def toggle_comment_like(session: AsyncSession, *, user_id: int, comment_id: int) -> dict[str, Any]:
    await _ensure_social_tables(session)

    comment_exists = await session.execute(
        text("SELECT id FROM feed_comments WHERE id = :comment_id LIMIT 1"),
        {"comment_id": comment_id},
    )
    if comment_exists.scalar_one_or_none() is None:
        raise ValueError("comment_not_found")

    existing_like = await session.execute(
        text(
            """
            SELECT id
            FROM feed_comment_likes
            WHERE comment_id = :comment_id AND user_id = :user_id
            LIMIT 1
            """
        ),
        {"comment_id": comment_id, "user_id": user_id},
    )
    existing_like_id = existing_like.scalar_one_or_none()

    if existing_like_id is not None:
        await session.execute(
            text("DELETE FROM feed_comment_likes WHERE id = :id"),
            {"id": existing_like_id},
        )
        liked = False
    else:
        now_sql = sql_timestamp_now(session)
        await session.execute(
            text(
                f"""
                INSERT INTO feed_comment_likes (comment_id, user_id, created_at)
                VALUES (:comment_id, :user_id, {now_sql})
                """
            ),
            {"comment_id": comment_id, "user_id": user_id},
        )
        liked = True

    like_count_result = await session.execute(
        text("SELECT COUNT(*) FROM feed_comment_likes WHERE comment_id = :comment_id"),
        {"comment_id": comment_id},
    )
    like_count = int(like_count_result.scalar_one() or 0)
    await session.commit()

    return {"comment_id": comment_id, "liked": liked, "like_count": like_count}
