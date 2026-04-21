import hashlib
from typing import Any
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.db.sql_helpers import sql_timestamp_now


RAW_NEWS_SELECT_COLUMNS = """
id, title, source_url, image_url, raw_text, category, region, is_urgent,
created_at, process_status, error_message, attempt_count, content_hash
"""


def build_content_hash(title: str, raw_text: str | None, source_url: str | None) -> str:
    payload = "|".join([title.strip(), (raw_text or "").strip(), (source_url or "").strip()])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _normalize_source_url(raw: str | None) -> str | None:
    if not raw:
        return None
    try:
        p = urlparse(raw)
    except Exception:
        return raw.strip()

    # normalize hostname to lowercase, strip fragment
    scheme = p.scheme or 'http'
    netloc = (p.netloc or '').lower()
    path = p.path or ''
    if path.endswith('/') and len(path) > 1:
        path = path.rstrip('/')

    # drop common tracking params
    params = [(k, v) for k, v in parse_qsl(p.query or '', keep_blank_values=True) if not (k.startswith('utm_') or k in ('fbclid', 'gclid'))]
    query = urlencode(params)
    return urlunparse((scheme, netloc, path, '', query, ''))


async def create_raw_news(session: AsyncSession, payload: dict[str, Any]) -> dict[str, Any]:
    source_url = payload.get("source_url") or None
    normalized_url = _normalize_source_url(source_url)

    # 1) If we have a source URL — try to find existing by URL first (simple dedupe by URL)
    if normalized_url:
        existing_by_url_q = """
        SELECT
            {columns}
        FROM raw_news
        WHERE source_url = :source_url
        ORDER BY id
        LIMIT 1
        """.format(columns=RAW_NEWS_SELECT_COLUMNS)
        existing_by_url = await session.execute(text(existing_by_url_q), {"source_url": normalized_url})
        existing_row = existing_by_url.mappings().first()
        if existing_row is not None:
            return dict(existing_row)

    # 2) Fallback: dedupe by content_hash (title|text|url)
    content_hash = build_content_hash(
        payload["title"],
        payload.get("raw_text"),
        normalized_url,
    )

    existing_query = """
    SELECT
        {columns}
    FROM raw_news
    WHERE content_hash = :content_hash
    ORDER BY id
    LIMIT 1
    """.format(columns=RAW_NEWS_SELECT_COLUMNS)
    existing_result = await session.execute(text(existing_query), {"content_hash": content_hash})
    existing_row = existing_result.mappings().first()
    if existing_row is not None:
        return dict(existing_row)

    now_sql = sql_timestamp_now(session)
    # Try atomic insert with ON CONFLICT DO NOTHING to avoid race conditions.
    insert_query_pg = f"""
    INSERT INTO raw_news (
        title, source_url, image_url, raw_text, category, region, is_urgent,
        created_at, process_status, error_message, attempt_count, content_hash
    )
    VALUES (
        :title, :source_url, :image_url, :raw_text, :category, :region, :is_urgent,
        {now_sql}, 'pending', NULL, 0, :content_hash
    )
    ON CONFLICT DO NOTHING
    RETURNING
        {RAW_NEWS_SELECT_COLUMNS}
    """

    params = {
        "title": payload["title"],
        # store normalized URL when possible
        "source_url": normalized_url or payload.get("source_url"),
        "image_url": payload.get("image_url"),
        "raw_text": payload.get("raw_text"),
        "category": payload.get("category"),
        "region": payload.get("region"),
        "is_urgent": payload.get("is_urgent", False),
        "content_hash": content_hash,
    }

    try:
        result = await session.execute(text(insert_query_pg), params)
        await session.commit()
    except Exception:
        # If INSERT with ON CONFLICT isn't supported or fails, fall back to safe INSERT without ON CONFLICT
        insert_query = f"""
        INSERT INTO raw_news (
            title, source_url, image_url, raw_text, category, region, is_urgent,
            created_at, process_status, error_message, attempt_count, content_hash
        )
        VALUES (
            :title, :source_url, :image_url, :raw_text, :category, :region, :is_urgent,
            {now_sql}, 'pending', NULL, 0, :content_hash
        )
        RETURNING
            {RAW_NEWS_SELECT_COLUMNS}
        """
        result = await session.execute(text(insert_query), params)
        await session.commit()

    row = result.mappings().first()
    if row is not None:
        return dict(row)

    # If insert returned nothing, it means a conflicting row exists — fetch it and return.
    if normalized_url:
        existing_by_url = await session.execute(text(existing_by_url_q), {"source_url": normalized_url})
        existing_row = existing_by_url.mappings().first()
        if existing_row is not None:
            print(f"[DUPLICATE] {normalized_url}")
            return dict(existing_row)

    # Fallback: query by content_hash (should find the conflicting row)
    existing_result = await session.execute(text(existing_query), {"content_hash": content_hash})
    existing_row = existing_result.mappings().first()
    if existing_row is not None:
        print(f"[DUPLICATE] content_hash={content_hash}")
        return dict(existing_row)

    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create raw news")
