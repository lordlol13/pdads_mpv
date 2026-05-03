import hashlib
import html
import logging
import re
from typing import Any
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode, urljoin

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.core.config import settings
from app.backend.db.sql_helpers import sql_timestamp_now

logger = logging.getLogger(__name__)

RAW_NEWS_SELECT_COLUMNS = """
id, title, source_url, image_url, image_hash, raw_text, category, region, is_urgent,
created_at, process_status, error_message, attempt_count, content_hash
"""

# Fallback select columns when DB doesn't have `image_hash` (migration not applied yet)
RAW_NEWS_SELECT_COLUMNS_NO_IMAGE = """
id, title, source_url, image_url, raw_text, category, region, is_urgent,
created_at, process_status, error_message, attempt_count, content_hash
"""

# Cache result of schema check to avoid repeated information_schema queries
_IMAGE_HASH_EXISTS: bool | None = None
_DB_URL_LOGGED = False


def get_image_hash(url: str | None) -> str | None:
    if not url:
        return None
    try:
        return hashlib.md5(url.strip().lower().encode("utf-8")).hexdigest()
    except Exception:
        return None


def _looks_like_logo_url(url: str | None) -> bool:
    value = (url or "").strip().lower()
    if not value:
        return False
    return any(token in value for token in ("logo", "favicon", "apple-touch-icon"))


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
    global _DB_URL_LOGGED
    if not _DB_URL_LOGGED:
        logger.info("[DB] using: %s", settings.DATABASE_URL)
        try:
            dialect_name = session.get_bind().dialect.name
            logger.info("[DB] dialect: %s", dialect_name)
            if dialect_name == "sqlite":
                logger.warning("[DB] sqlite detected, expected PostgreSQL")
        except Exception:
            pass
        _DB_URL_LOGGED = True

    source_url = payload.get("source_url") or None
    normalized_url = _normalize_source_url(source_url)

    def clean_text(text: str | None) -> str:
        if not text:
            return ""
        text = html.unescape(str(text))
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    # sanitize and normalize provided image URL (protect against short/broken values)
    image_url = payload.get("image_url") or None
    if image_url:
        image_url = image_url.strip()
        if len(image_url) < 10:
            image_url = None
        elif image_url.startswith("//"):
            image_url = "https:" + image_url
        elif image_url.startswith("/") and (normalized_url or source_url):
            image_url = urljoin(normalized_url or source_url, image_url)
    if _looks_like_logo_url(image_url):
        logger.warning("[DEBUG] image_url looks like logo, dropping it: %s", image_url)
        image_url = None

    image_hash = get_image_hash(image_url)

    # Determine whether DB has `image_hash` column (cache the result)
    global _IMAGE_HASH_EXISTS
    if _IMAGE_HASH_EXISTS is None:
        try:
            q = """
            SELECT 1 FROM information_schema.columns
            WHERE table_name = 'raw_news' AND column_name = 'image_hash'
            LIMIT 1
            """
            res = await session.execute(text(q))
            _IMAGE_HASH_EXISTS = bool(res.scalar())
        except Exception:
            _IMAGE_HASH_EXISTS = False

    # choose columns SQL based on schema
    select_columns = RAW_NEWS_SELECT_COLUMNS if _IMAGE_HASH_EXISTS else RAW_NEWS_SELECT_COLUMNS_NO_IMAGE

    now_sql = sql_timestamp_now(session)
    # Ensure unique index exists on source_url to enable ON CONFLICT (source_url)
    try:
        await session.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_news_url ON raw_news(source_url);"))
        await session.commit()
    except Exception:
        try:
            await session.rollback()
        except Exception:
            pass
    # Atomic insert. No pre-filtering before insert.
    if _IMAGE_HASH_EXISTS:
        insert_query_pg = f"""
        INSERT INTO raw_news (
            title, source_url, image_url, image_hash, raw_text, category, region, is_urgent,
            created_at, process_status, error_message, attempt_count
        )
        VALUES (
            :title, :source_url, :image_url, :image_hash, :raw_text, :category, :region, :is_urgent,
            {now_sql}, 'pending', NULL, 0
        )
        ON CONFLICT (source_url) DO NOTHING
        RETURNING
            {select_columns}
        """
    else:
        insert_query_pg = f"""
        INSERT INTO raw_news (
            title, source_url, image_url, raw_text, category, region, is_urgent,
            created_at, process_status, error_message, attempt_count
        )
        VALUES (
            :title, :source_url, :image_url, :raw_text, :category, :region, :is_urgent,
            {now_sql}, 'pending', NULL, 0
        )
        ON CONFLICT (source_url) DO NOTHING
        RETURNING
            {select_columns}
        """

    # Clean text before saving to DB
    cleaned_raw_text = clean_text(payload.get("raw_text"))
    cleaned_title = clean_text(payload.get("title"))

    params = {
        "title": cleaned_title,
        # store normalized URL when possible
        "source_url": normalized_url or payload.get("source_url"),
        "image_url": image_url,
        "image_hash": image_hash,
        "raw_text": cleaned_raw_text,
        "category": payload.get("category"),
        "region": payload.get("region"),
        "is_urgent": payload.get("is_urgent", False),
    }
    print(f"[DEBUG] SAVING: {params['title']}")
    print(f"[DEBUG] SAVING image_url: {params.get('image_url')}")

    try:
        result = await session.execute(text(insert_query_pg), params)
        await session.commit()
    except Exception as e:
        logger.exception("[ERROR] create_raw_news primary insert failed: %s", e)
        print(f"[ERROR] create_raw_news: {e}")
        try:
            await session.rollback()
        except Exception:
            pass
        raise

    row = result.mappings().first()
    if row is not None:
        try:
            logger.info("[PIPELINE] raw_news inserted: %s", row.get("id"))
        except Exception:
            pass
        return dict(row)

    # Conflict path: fetch existing row by URL and report duplicate.
    if normalized_url:
        existing_by_url_q = """
        SELECT
            {columns}
        FROM raw_news
        WHERE source_url = :source_url
        ORDER BY id
        LIMIT 1
        """.format(columns=select_columns)
        existing_by_url = await session.execute(text(existing_by_url_q), {"source_url": normalized_url})
        existing_row = existing_by_url.mappings().first()
        logger.info("[INGESTION] skipped duplicate url=%s", normalized_url or source_url)
        if existing_row is not None:
            return dict(existing_row)

    raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create raw news")


async def insert_test_raw_news(session: AsyncSession) -> None:
    await session.execute(
        text("""
        INSERT INTO raw_news (title, source_url, raw_text, created_at)
        VALUES ('TEST NEWS', 'test-url-' || random()::text, 'test text', NOW())
        """)
    )
    await session.commit()
