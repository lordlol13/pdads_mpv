from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Sequence

from openai import AsyncOpenAI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.core.config import settings
from app.backend.db.sql_helpers import sql_timestamp_now


EMBEDDING_MODEL_NAME = "hash-256-v1"

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "before",
    "by",
    "for",
    "from",
    "has",
    "have",
    "he",
    "her",
    "his",
    "i",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "she",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "to",
    "was",
    "were",
    "will",
    "with",
    "yangilik",
    "yangiliklar",
    "news",
    "novost",
    "новость",
    "today",
    "update",
    "latest",
    "report",
    "story",
}


def _normalize_text(value: str | None) -> str:
    raw = str(value or "")
    raw = raw.replace("\r", "\n")
    raw = re.sub(r"\[\+\d+\s+chars\]", "", raw, flags=re.IGNORECASE)
    raw = re.sub(r"\s+", " ", raw)
    return raw.strip()


def _tokenize(value: str | None) -> list[str]:
    text_value = _normalize_text(value).lower()
    if not text_value:
        return []

    tokens = [token for token in re.findall(r"[\w']+", text_value) if token]
    filtered = [token for token in tokens if len(token) >= 2 and token not in STOPWORDS]
    return filtered


def _feature_index(feature: str, dimension: int) -> int:
    digest = hashlib.sha256(feature.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big", signed=False) % max(1, dimension)


def _normalize_vector(vector: Sequence[float]) -> list[float]:
    values = [float(value or 0.0) for value in vector]
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0.0:
        return [0.0 for _ in values]
    return [round(value / norm, 8) for value in values]


def _add_feature(vector: list[float], feature: str, weight: float) -> None:
    index = _feature_index(feature, len(vector))
    vector[index] += weight


def text_to_embedding(text_value: str | None, *, dimension: int | None = None) -> list[float]:
    vector_dimension = int(dimension or settings.EMBEDDING_DIMENSION or 256)
    vector_dimension = max(32, vector_dimension)
    vector = [0.0 for _ in range(vector_dimension)]

    tokens = _tokenize(text_value)
    if not tokens:
        return vector

    token_count = len(tokens)
    token_weight = 1.0 / math.sqrt(max(1, token_count))

    for index, token in enumerate(tokens):
        _add_feature(vector, f"tok:{token}", token_weight)

        if index + 1 < token_count:
            bigram = f"{token}:{tokens[index + 1]}"
            _add_feature(vector, f"bi:{bigram}", token_weight * 1.2)

        if index + 2 < token_count:
            trigram = f"{token}:{tokens[index + 1]}:{tokens[index + 2]}"
            _add_feature(vector, f"tri:{trigram}", token_weight * 0.8)

    return _normalize_vector(vector)


def _build_openai_embedding_client() -> tuple[AsyncOpenAI | None, str | None]:
    if settings.OPENAI_API_KEY.strip():
        return AsyncOpenAI(api_key=settings.OPENAI_API_KEY), settings.OPENAI_EMBEDDING_MODEL
    return None, None


async def text_to_embedding_async(text_value: str | None) -> tuple[list[float], str]:
    normalized = _normalize_text(text_value)
    if not normalized:
        return text_to_embedding(normalized), EMBEDDING_MODEL_NAME

    client, model_name = _build_openai_embedding_client()
    if client is None or not model_name:
        return text_to_embedding(normalized), EMBEDDING_MODEL_NAME

    try:
        response = await client.embeddings.create(
            model=model_name,
            input=normalized,
        )
        vector = list(response.data[0].embedding) if response.data else []
        if not vector:
            return text_to_embedding(normalized), EMBEDDING_MODEL_NAME
        return _normalize_vector(vector), model_name
    except Exception:
        return text_to_embedding(normalized), EMBEDDING_MODEL_NAME


def vector_to_json(vector: Sequence[float]) -> str:
    return json.dumps([round(float(value or 0.0), 8) for value in vector], ensure_ascii=False)


def vector_from_json(value: Any) -> list[float] | None:
    if isinstance(value, list):
        try:
            return [float(item or 0.0) for item in value]
        except (TypeError, ValueError):
            return None

    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, list):
            return vector_from_json(parsed)

    return None


def cosine_similarity(left: Sequence[float] | None, right: Sequence[float] | None) -> float:
    left_vector = [float(value or 0.0) for value in (left or [])]
    right_vector = [float(value or 0.0) for value in (right or [])]
    if not left_vector or not right_vector:
        return 0.0

    limit = min(len(left_vector), len(right_vector))
    if limit <= 0:
        return 0.0

    dot = sum(left_vector[index] * right_vector[index] for index in range(limit))
    left_norm = math.sqrt(sum(value * value for value in left_vector[:limit]))
    right_norm = math.sqrt(sum(value * value for value in right_vector[:limit]))
    if left_norm <= 0.0 or right_norm <= 0.0:
        return 0.0
    return round(dot / (left_norm * right_norm), 6)


def _weighted_average(vectors: Iterable[tuple[Sequence[float], float]]) -> list[float]:
    collected = [(list(vector), float(weight or 0.0)) for vector, weight in vectors if vector and float(weight or 0.0) != 0.0]
    if not collected:
        return []

    dimension = max(len(vector) for vector, _weight in collected)
    accumulator = [0.0 for _ in range(dimension)]
    total_weight = 0.0

    for vector, weight in collected:
        total_weight += abs(weight)
        for index, value in enumerate(vector[:dimension]):
            accumulator[index] += value * weight

    if total_weight <= 0.0:
        return []

    return _normalize_vector(accumulator)


def _parse_json_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return parsed
    return {}


def build_news_embedding_text(
    *,
    title: str,
    final_text: str,
    category: str | None = None,
    target_persona: str | None = None,
    raw_text: str | None = None,
    region: str | None = None,
) -> str:
    parts = [
        f"title: {title}",
        f"category: {category or 'general'}",
        f"persona: {target_persona or 'general'}",
        f"region: {region or ''}",
        f"body: {final_text}",
        f"source: {raw_text or ''}",
    ]
    return _normalize_text(" \n".join(part for part in parts if part))


def build_user_profile_text(
    *,
    interests: Any = None,
    location: str | None = None,
    country_code: str | None = None,
    region_code: str | None = None,
    username: str | None = None,
) -> str:
    payload = _parse_json_payload(interests)
    parts: list[str] = []

    for key in ("all_topics", "topics", "custom_topics"):
        values = payload.get(key)
        if isinstance(values, list):
            parts.extend(str(item).strip().lower() for item in values if str(item).strip())

    profession = str(payload.get("profession") or "").strip().lower()
    if profession:
        parts.append(profession)

    country_name = str(payload.get("country_name") or "").strip().lower()
    if country_name:
        parts.append(country_name)

    city = str(payload.get("city") or "").strip().lower()
    if city:
        parts.append(city)

    if location:
        parts.append(str(location).strip().lower())
    if country_code:
        parts.append(str(country_code).strip().lower())
    if region_code:
        parts.append(str(region_code).strip().lower())
    if username:
        parts.append(str(username).strip().lower())

    return _normalize_text(" ".join(part for part in parts if part))


def _news_row_embedding_text(row: dict[str, Any]) -> str:
    return build_news_embedding_text(
        title=str(row.get("final_title") or row.get("title") or ""),
        final_text=str(row.get("final_text") or row.get("raw_text") or ""),
        category=str(row.get("category") or "general"),
        target_persona=str(row.get("target_persona") or "general"),
        raw_text=str(row.get("raw_text") or ""),
        region=str(row.get("region") or ""),
    )


def _news_weight_from_signal(row: dict[str, Any]) -> float:
    liked = row.get("liked")
    viewed = bool(row.get("viewed"))
    saved = bool(row.get("saved"))
    watch_time = float(row.get("watch_time") or 0.0)

    weight = 0.35 if viewed else 0.0
    if liked is True:
        weight += 2.25
    elif liked is False:
        weight -= 1.2
    if saved:
        weight += 1.4
    if watch_time > 0:
        weight += min(watch_time / 240.0, 0.5)
    return weight


def _freshness_score(created_at: Any) -> float:
    if not created_at:
        return 0.0

    if isinstance(created_at, str):
        try:
            created = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError:
            return 0.0
    elif isinstance(created_at, datetime):
        created = created_at
    else:
        return 0.0

    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    age_hours = max(0.0, (datetime.now(timezone.utc) - created.astimezone(timezone.utc)).total_seconds() / 3600.0)
    # Exponential decay over roughly 48 hours.
    return round(math.exp(-age_hours / 48.0), 6)


async def refresh_ai_news_embedding(
    session: AsyncSession,
    ai_news_id: int,
    *,
    title: str,
    final_text: str,
    category: str | None = None,
    target_persona: str | None = None,
    raw_text: str | None = None,
    region: str | None = None,
) -> list[float]:
    text_value = build_news_embedding_text(
        title=title,
        final_text=final_text,
        category=category,
        target_persona=target_persona,
        raw_text=raw_text,
        region=region,
    )
    vector, model_name = await text_to_embedding_async(text_value)
    timestamp_sql = sql_timestamp_now(session)

    await session.execute(
        text(
            f"""
            UPDATE ai_news
            SET embedding_vector = :embedding_vector,
                embedding_model = :embedding_model,
                embedding_updated_at = {timestamp_sql},
                vector_status = 'indexed'
            WHERE id = :ai_news_id
            """
        ),
        {
            "ai_news_id": ai_news_id,
            "embedding_vector": vector_to_json(vector),
            "embedding_model": model_name,
        },
    )
    await session.commit()
    return vector


async def refresh_user_embedding(
    session: AsyncSession,
    user_id: int,
    *,
    history_limit: int | None = None,
) -> list[float]:
    limit = max(5, int(history_limit or settings.RECOMMENDER_USER_HISTORY_LIMIT or 20))

    user_result = await session.execute(
        text(
            """
            SELECT id, username, interests, location, country_code, region_code, embedding_vector
            FROM users
            WHERE id = :user_id
            LIMIT 1
            """
        ),
        {"user_id": user_id},
    )
    user_row = user_result.mappings().first()
    if user_row is None:
        return []

    profile_text = build_user_profile_text(
        interests=user_row.get("interests"),
        location=user_row.get("location"),
        country_code=user_row.get("country_code"),
        region_code=user_row.get("region_code"),
        username=user_row.get("username"),
    )
    profile_vector: list[float]
    if profile_text:
        profile_vector, model_name = await text_to_embedding_async(profile_text)
    else:
        profile_vector, model_name = ([], EMBEDDING_MODEL_NAME)

    interactions_result = await session.execute(
        text(
            """
            SELECT
                i.liked,
                i.viewed,
                i.watch_time,
                i.created_at,
                an.final_title,
                an.final_text,
                rn.raw_text,
                an.category,
                an.target_persona,
                rn.region,
                an.embedding_vector
            FROM interactions i
            JOIN ai_news an ON an.id = i.ai_news_id
            JOIN raw_news rn ON rn.id = an.raw_news_id
            WHERE i.user_id = :user_id
            ORDER BY i.created_at DESC, i.id DESC
            LIMIT :limit
            """
        ),
        {"user_id": user_id, "limit": limit},
    )
    interaction_rows = [dict(row) for row in interactions_result.mappings().all()]

    saved_result = await session.execute(
        text(
            """
            SELECT
                sn.created_at,
                an.final_title,
                an.final_text,
                rn.raw_text,
                an.category,
                an.target_persona,
                rn.region,
                an.embedding_vector
            FROM saved_news sn
            JOIN ai_news an ON an.id = sn.ai_news_id
            JOIN raw_news rn ON rn.id = an.raw_news_id
            WHERE sn.user_id = :user_id
            ORDER BY sn.created_at DESC, sn.id DESC
            LIMIT :limit
            """
        ),
        {"user_id": user_id, "limit": limit},
    )
    saved_rows = [dict(row) for row in saved_result.mappings().all()]

    weighted_vectors: list[tuple[Sequence[float], float]] = []
    if profile_vector:
        weighted_vectors.append((profile_vector, 1.8))

    for row in interaction_rows:
        vector = vector_from_json(row.get("embedding_vector"))
        if not vector:
            vector = text_to_embedding(_news_row_embedding_text(row))
        weight = _news_weight_from_signal(row)
        if vector and weight:
            weighted_vectors.append((vector, weight))

    seen_saved_titles: set[str] = set()
    for row in saved_rows:
        title_key = _normalize_text(str(row.get("final_title") or "")).lower()
        if title_key and title_key in seen_saved_titles:
            continue
        if title_key:
            seen_saved_titles.add(title_key)

        vector = vector_from_json(row.get("embedding_vector"))
        if not vector:
            vector = text_to_embedding(_news_row_embedding_text(row))
        if vector:
            weighted_vectors.append((vector, 1.35))

    vector = _weighted_average(weighted_vectors)
    if not vector:
        if profile_vector:
            vector = profile_vector
        else:
            vector, model_name = await text_to_embedding_async(profile_text)

    timestamp_sql = sql_timestamp_now(session)
    await session.execute(
        text(
            f"""
            UPDATE users
            SET embedding_vector = :embedding_vector,
                embedding_model = :embedding_model,
                embedding_updated_at = {timestamp_sql}
            WHERE id = :user_id
            """
        ),
        {
            "user_id": user_id,
            "embedding_vector": vector_to_json(vector),
            "embedding_model": model_name,
        },
    )
    await session.commit()
    return vector


async def ensure_user_embedding(session: AsyncSession, user_id: int) -> list[float]:
    result = await session.execute(
        text(
            """
            SELECT embedding_vector
            FROM users
            WHERE id = :user_id
            LIMIT 1
            """
        ),
        {"user_id": user_id},
    )
    row = result.mappings().first()
    vector = vector_from_json(row.get("embedding_vector")) if row else None
    if vector:
        return _normalize_vector(vector)
    return await refresh_user_embedding(session, user_id)


def rank_feed_rows(
    rows: list[dict[str, Any]],
    *,
    user_embedding: Sequence[float] | None,
    limit: int,
    user_topics: list[str] | None = None,
) -> list[dict[str, Any]]:
    if not rows:
        return []

    normalized_user_embedding = _normalize_vector(user_embedding or []) if user_embedding else []
    normalized_topics = [str(topic).strip().lower() for topic in (user_topics or []) if str(topic).strip()]
    topic_set = {topic for topic in normalized_topics if topic and topic != "general"}
    top_similarity_window = max(limit, int(limit * max(1, settings.RECOMMENDER_SIMILARITY_WINDOW_MULTIPLIER)))

    scored_rows: list[dict[str, Any]] = []
    for row in rows:
        candidate = dict(row)
        news_vector = vector_from_json(candidate.get("embedding_vector"))
        if not news_vector:
            news_vector = text_to_embedding(_news_row_embedding_text(candidate))

        similarity = cosine_similarity(normalized_user_embedding, news_vector) if normalized_user_embedding else 0.0
        engagement = 0.0
        if bool(candidate.get("saved")):
            engagement += 1.0
        if candidate.get("liked") is True:
            engagement += 1.25
        elif candidate.get("liked") is False:
            engagement -= 0.5
        if bool(candidate.get("viewed")):
            engagement += 0.25
        engagement += min(float(candidate.get("comment_count") or 0) * 0.03, 0.25)

        freshness = _freshness_score(candidate.get("created_at"))
        final_score = (
            float(settings.RECOMMENDER_SIMILARITY_WEIGHT) * similarity
            + float(settings.RECOMMENDER_ENGAGEMENT_WEIGHT) * engagement
            + float(settings.RECOMMENDER_FRESHNESS_WEIGHT) * freshness
        )

        candidate["similarity_score"] = round(similarity, 6)
        candidate["engagement_score"] = round(engagement, 6)
        candidate["freshness_score"] = round(freshness, 6)
        candidate["rank_score"] = round(final_score, 6)
        scored_rows.append(candidate)

    scored_rows.sort(key=lambda item: float(item.get("similarity_score") or 0.0), reverse=True)
    candidate_window = scored_rows[:top_similarity_window]

    filtered: list[dict[str, Any]] = []
    for row in candidate_window:
        saved = bool(row.get("saved"))
        viewed = bool(row.get("viewed"))
        persona = str(row.get("target_persona") or "").strip().lower()

        if normalized_topics and not saved:
            if topic_set and not any(
                topic == persona or persona.startswith(f"{topic}|") or persona.startswith(f"{topic},")
                for topic in topic_set
            ):
                continue

        if viewed and not saved:
            continue

        filtered.append(row)

    if not filtered:
        filtered = candidate_window

    filtered.sort(
        key=lambda item: (
            float(item.get("rank_score") or 0.0),
            float(item.get("similarity_score") or 0.0),
            float(item.get("ai_score") or 0.0),
            int(item.get("user_feed_id") or 0),
        ),
        reverse=True,
    )
    return filtered[:limit]
