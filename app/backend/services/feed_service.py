import json
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.db.sql_helpers import sql_timestamp_now


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


async def get_user_feed(session: AsyncSession, user_id: int, limit: int = 50) -> list[dict[str, Any]]:
    await _ensure_social_tables(session)

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
        an.vector_status,
        li.liked,
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
    WHERE uf.user_id = :user_id
        AND NOT (COALESCE(li.viewed, FALSE) = TRUE AND sn.id IS NULL)
    ORDER BY rank_score DESC, uf.id DESC
    LIMIT :limit
    """
    result = await session.execute(text(query), {"user_id": user_id, "limit": limit})
    rows = [dict(row) for row in result.mappings().all()]

    if not user_topics:
        return rows

    filtered: list[dict[str, Any]] = []
    for row in rows:
        if bool(row.get("saved")):
            filtered.append(row)
            continue
        if _persona_matches_topics(row.get("target_persona"), user_topics):
            filtered.append(row)

    return filtered


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
