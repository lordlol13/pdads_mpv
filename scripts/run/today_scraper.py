#!/usr/bin/env python3
"""
Асинхронный скрипт: собрать только статьи, опубликованные сегодня.
Сохранит результаты в data/processed/parsed_today.json.
"""
from __future__ import annotations
import argparse
import asyncio
import json
import logging
from typing import List
from app.backend.services.today_pipeline_utils import find_today_articles

# Импортируем лениво для опциональной записи в БД
_DB_SESSION_IMPORT = "app.backend.db.session"
_DB_INGEST_IMPORT = "app.backend.services.db_ingest"

LOG = logging.getLogger("today_scraper")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

FRONTPAGES: List[str] = [
    "https://gazeta.uz/ru/",
    "https://daryo.uz/",
    "https://uz24.uz/",
    "https://uznews.uz/",
    "https://kun.uz/",
    "https://podrobno.uz/",
]

# Safety cap: максимальное число записей, которое будет сохранено за один запуск,
# даже если пользователь не указал --limit. Помогает избежать случайных массовых вставок.
MAX_SAVE_CAP = 200

def save_results(results, out_path: str = "data/processed/parsed_today.json") -> None:
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(results, fh, ensure_ascii=False, indent=2)
    LOG.info("saved %d articles to %s", len(results), out_path)

def main():
    parser = argparse.ArgumentParser(description="Собрать сегодняшние статьи и опционально сохранить в БД")
    parser.add_argument("--save", action="store_true", help="Сохранить найденные статьи в БД (одна сессия)")
    parser.add_argument("--out", default="data/processed/parsed_today.json", help="Путь для сохранения JSON")
    parser.add_argument("--limit", type=int, default=0, help="Ограничение на число записей, сохраняемых в БД (0 = без ограничения)")
    parser.add_argument("--domains", type=str, default=None, help="CSV списка доменов для сохранения (например: gazeta.uz,daryo.uz)")
    args = parser.parse_args()

    try:
        results = asyncio.run(find_today_articles())
    except TypeError:
        results = asyncio.run(find_today_articles(FRONTPAGES))

    save_results(results, args.out)

    # Подсчёт и вывод общего числа найденных
    total_found = len(results)
    LOG.info("total scraped: %d", total_found)

    counts = {}
    for r in results:
        src = r.get("source")
        counts[src] = counts.get(src, 0) + 1
    for k, v in counts.items():
        print(f"{k} -> found today articles: {v}")

    # final stable log for monitoring
    print(f"[FINAL] total={len(results)} by source={counts}")

    if args.save and results:
        try:
            # ленивый импорт, чтобы не тянуть DB-зависимости для обычного dry-run
            from importlib import import_module
            from urllib.parse import urlparse

            def _netloc(url: str) -> str:
                try:
                    return urlparse(url).netloc or ""
                except Exception:
                    return ""

            # Фильтрация по доменам
            filtered = results
            if args.domains:
                wanted = [d.strip() for d in args.domains.split(",") if d.strip()]
                if wanted:
                    def _matches_domain(src: str) -> bool:
                        net = _netloc(src or "")
                        for w in wanted:
                            if net.endswith(w):
                                return True
                        return False

                    filtered = [r for r in results if _matches_domain(r.get("source") or "")]

            # Ограничение количества записей, которые будут сохранены в БД
            requested = args.limit if args.limit and args.limit > 0 else MAX_SAVE_CAP
            final_limit = min(requested, MAX_SAVE_CAP)
            to_save = filtered[: final_limit] if final_limit and final_limit > 0 else filtered
            LOG.info("saving to DB: %d (final_limit=%d requested=%d domains=%r)", len(to_save), final_limit, args.limit or 0, args.domains)

            # Нормализация: привести поля к формату, который ожидает `save_news`
            normalized: List[dict] = []
            for it in to_save:
                src = it.get("source_url") or it.get("url") or None
                if not src:
                    LOG.debug("skip item without URL during normalization: %r", it.get("title"))
                    continue
                norm_item = {
                    "title": it.get("title"),
                    "source_url": src,
                    "image_url": it.get("image_url") or it.get("image") or it.get("img") or None,
                    "raw_text": it.get("raw_text") or it.get("content") or it.get("text") or "",
                    "category": it.get("category") or it.get("section"),
                    "region": it.get("region"),
                    "is_urgent": bool(it.get("is_urgent", False)),
                }
                normalized.append(norm_item)

            to_save = normalized
            LOG.info("normalized to_save: %d items", len(to_save))

            session_module = import_module(_DB_SESSION_IMPORT)
            ingest_module = import_module(_DB_INGEST_IMPORT)
            SessionLocal = getattr(session_module, "SessionLocal")
            save_news = getattr(ingest_module, "save_news")

            async def _save():
                # Выполнить сохранение и затем выполнить базовые проверки целостности
                from sqlalchemy import text

                async with SessionLocal() as session:
                    stats = await save_news(session, to_save)
                    LOG.info("DB save stats: %s", stats)

                    inserted = stats.get("inserted", 0)
                    skipped = stats.get("skipped", 0)
                    total_stats = stats.get("total", len(to_save))
                    print(f"[DB] inserted={inserted}, skipped={skipped}, total={total_stats}")

                    # Проверить дубликаты среди только что сохранённых URL
                    urls = [r.get("source_url") for r in to_save if r.get("source_url")]
                    if urls:
                        params = {f"u{i}": v for i, v in enumerate(urls)}
                        placeholders = ", ".join(":" + k for k in params.keys())
                        dup_q = text(f"SELECT source_url, COUNT(*) AS cnt FROM raw_news WHERE source_url IN ({placeholders}) GROUP BY source_url HAVING COUNT(*) > 1")
                        dup_res = await session.execute(dup_q, params)
                        dup_rows = dup_res.mappings().all()
                        if dup_rows:
                            print("[DB DUPLICATES] Found duplicates for saved URLs:")
                            for r in dup_rows:
                                print(f" - {r['source_url']} count={r['cnt']}")
                        else:
                            print("[DB DUPLICATES] none found for saved URLs")

                    # Выбрать 2-3 примеров из БД для ручной проверки
                    inserted_rows = stats.get("inserted_rows", []) or []
                    sample_ids = [r.get("id") for r in inserted_rows[:3] if r.get("id")]
                    if sample_ids:
                        params = {f"id{i}": v for i, v in enumerate(sample_ids)}
                        placeholders = ", ".join(":" + k for k in params.keys())
                        sample_q = text(f"SELECT id, title, source_url, LENGTH(COALESCE(raw_text,'')) AS raw_len, image_url, created_at FROM raw_news WHERE id IN ({placeholders})")
                        sample_res = await session.execute(sample_q, params)
                        sample_rows = sample_res.mappings().all()
                        print("[DB SAMPLE ROWS]")
                        for r in sample_rows:
                            raw_len = r.get("raw_len")
                            print(f" id={r.get('id')} url={r.get('source_url')} title={str(r.get('title'))[:120]} raw_len={raw_len} image_url={'yes' if r.get('image_url') else 'no'} created_at={r.get('created_at')}")
                    else:
                        print("[DB SAMPLE ROWS] no inserted rows returned")

            asyncio.run(_save())
        except Exception:
            LOG.exception("saving to DB failed")

if __name__ == "__main__":
    main()
