"""Утилиты для безопасного пакетного сохранения собранных новостей в таблицу ``raw_news``.

Реализация ориентирована на производительность и надёжность:
- дедупликация входных данных по `source_url` (первая запись для одного URL — берётся),
- подсчёт `content_hash` для защиты на уровне БД,
- пакетная multi-row вставка `INSERT ... ON CONFLICT DO NOTHING` (используется
  существующий constraint `uq_raw_news_content_hash`),
- повторные попытки для временных ошибок БД,
- единая `AsyncSession`, передающаяся извне (функция не открывает сессию сама).
"""

from __future__ import annotations

from typing import Any, Dict, List
import logging
import asyncio

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.services.ingestion_service import build_content_hash
from app.backend.db.sql_helpers import sql_timestamp_now

LOG = logging.getLogger("db_ingest")


def _chunked(iterable: List[Any], size: int):
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]


async def save_news(
    session: AsyncSession,
    items: List[Dict[str, Any]],
    *,
    insert_batch_size: int = 200,
    max_retries: int = 3,
    retry_backoff: float = 0.5,
) -> Dict[str, Any]:
    """Efficient bulk save for scraped news.

    Args:
        session: AsyncSession — внешняя сессия, не создаётся внутри.
        items: список payload'ов с ключами: title, source_url, image_url, raw_text, category, region, is_urgent.
        insert_batch_size: максимальное число строк в одном INSERT.
        max_retries: число попыток при временной ошибке.
        retry_backoff: базовая пауза между попытками (умножается на номер попытки).

    Returns:
        dict: {"total", "inserted", "skipped", "inserted_rows"}
    """
    if not items:
        return {"total": 0, "inserted": 0, "skipped": 0, "inserted_rows": []}

    total = len(items)

    # Deduplicate by source_url (first seen wins)
    candidates_by_url: Dict[str, Dict[str, Any]] = {}
    skipped_no_url = 0
    for it in items:
        url = (it.get("source_url") or "").strip() if it.get("source_url") is not None else ""
        if not url:
            skipped_no_url += 1
            LOG.debug("skip item without source_url: %r", it.get("title"))
            continue
        if url in candidates_by_url:
            continue
        candidates_by_url[url] = {
            "title": (it.get("title") or "").strip(),
            "source_url": url,
            "image_url": it.get("image_url"),
            "raw_text": it.get("raw_text"),
            "category": it.get("category"),
            "region": it.get("region"),
            "is_urgent": bool(it.get("is_urgent", False)),
        }

    deduped_count = len(candidates_by_url)

    # Prepare insert candidates and compute content_hash
    to_insert: List[Dict[str, Any]] = []
    for rec in candidates_by_url.values():
        rec_copy = rec.copy()
        rec_copy["content_hash"] = build_content_hash(rec_copy["title"], rec_copy.get("raw_text"), rec_copy["source_url"])  # type: ignore[arg-type]
        to_insert.append(rec_copy)

    if not to_insert:
        LOG.info("save_news: nothing to insert — total=%d deduped=%d skipped_no_url=%d", total, deduped_count, skipped_no_url)
        return {"total": total, "inserted": 0, "skipped": total, "inserted_rows": []}

    now_sql = sql_timestamp_now(session)

    # Поля, которые подставляются как параметры (content_hash добавляем отдельно
    # в конец VALUES, чтобы совпадать с порядком колонок в INSERT)
    fields = [
        "title",
        "source_url",
        "image_url",
        "raw_text",
        "category",
        "region",
        "is_urgent",
    ]

    inserted_rows: List[Dict[str, Any]] = []

    # Batch multi-row INSERT
    for batch in _chunked(to_insert, insert_batch_size):
        params: Dict[str, Any] = {}
        values_placeholders: List[str] = []
        for i, rec in enumerate(batch):
            ph = []
            for f in fields:
                key = f"{f}_{i}"
                params[key] = rec.get(f)
                ph.append(f":{key}")
            # content_hash: добавляем отдельно, чтобы он оказался в конце VALUES
            content_key = f"content_hash_{i}"
            params[content_key] = rec.get("content_hash")
            # created_at and process_status are fixed; content_hash goes last
            row_place = "(" + ", ".join(ph) + f", {now_sql}, 'pending', NULL, 0, :{content_key})"
            values_placeholders.append(row_place)

        values_clause = ", ".join(values_placeholders)
        insert_sql = f"""
        INSERT INTO raw_news (
            title, source_url, image_url, raw_text, category, region, is_urgent,
            created_at, process_status, error_message, attempt_count, content_hash
        )
        VALUES {values_clause}
        ON CONFLICT DO NOTHING
        RETURNING id, title, source_url, image_url, raw_text, category, region, is_urgent, created_at, process_status, error_message, attempt_count, content_hash
        """

        # Retry loop per batch
        for attempt in range(1, max_retries + 1):
            try:
                async with session.begin():
                    res = await session.execute(text(insert_sql), params)
                    rows = res.mappings().all()
                    if rows:
                        inserted_rows.extend([dict(r) for r in rows])
                break
            except Exception:
                LOG.exception("batch insert attempt %d failed (size=%d)", attempt, len(batch))
                if attempt >= max_retries:
                    LOG.error("batch insert failed after %d attempts — skipping batch", max_retries)
                else:
                    await asyncio.sleep(retry_backoff * attempt)
                    continue

    inserted = len(inserted_rows)
    skipped = total - inserted
    LOG.info("save_news: total=%d deduped=%d inserted=%d skipped=%d skipped_no_url=%d", total, deduped_count, inserted, skipped, skipped_no_url)
    return {"total": total, "inserted": inserted, "skipped": skipped, "inserted_rows": inserted_rows}
