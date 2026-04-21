#!/usr/bin/env python3
"""Проверка kun.uz ссылок: быстрый filter + глубокая HTML-проверка.

Запускает проверки для ссылок из `scripts/parsed_today.json`.
Сохраняет результаты в `scripts/kun_validation.json` и сводку в `scripts/kun_validation_summary.json`.
"""

from __future__ import annotations
import asyncio
import json
from pathlib import Path
from collections import defaultdict
import httpx

from app.backend.services.article_detector import ArticleDetector

INPUT = Path("data/processed/parsed_today.json")
OUT_JSON = Path("data/debug/kun_validation.json")
OUT_SUMMARY = Path("data/debug/kun_validation_summary.json")
MAX_CHECKS = 50
CONCURRENCY = 8
TIMEOUT = 10.0


async def fetch_html(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        # Попытка HEAD сначала — быстрый фильтр по Content-Type
        try:
            h = await client.head(url, timeout=TIMEOUT, follow_redirects=True)
        except Exception:
            h = None

        if h is not None and h.status_code == 200:
            ct = h.headers.get("content-type", "")
            if "html" not in ct.lower():
                return None
        # Если HEAD вернул 405/не поддерживается или не дали Content-Type — сделать GET
        r = await client.get(url, timeout=TIMEOUT, follow_redirects=True)
        if r.status_code != 200:
            return None
        ct2 = r.headers.get("content-type", "")
        if "html" not in ct2.lower():
            return None
        return r.text
    except Exception:
        return None


async def main() -> None:
    if not INPUT.exists():
        print(f"{INPUT} not found")
        return

    data = json.loads(INPUT.read_text(encoding="utf-8"))

    # собрать kun.uz записи (unik urls)
    kun_items = [it for it in data if (it.get("source") or "").lower().startswith("https://kun.uz")]

    seen = set()
    urls_meta = []
    for it in kun_items:
        u = it.get("url")
        if not u:
            continue
        if u in seen:
            continue
        seen.add(u)
        urls_meta.append({"url": u, "title": it.get("title"), "published_at": it.get("published_at")})

    total_before = len(urls_meta)

    det = ArticleDetector()

    # быстрый фильтр по URL
    cheap_candidates = [u["url"] for u in urls_meta if det.is_article_url(u["url"])]
    cheap_count = len(cheap_candidates)

    to_check = cheap_candidates[:MAX_CHECKS]

    results: dict[str, dict] = {}

    sem = asyncio.Semaphore(CONCURRENCY)

    async with httpx.AsyncClient(headers={"User-Agent": "pdads-bot/1.0 (article-detector)"}) as client:
        async def worker(url: str) -> None:
            async with sem:
                html = await fetch_html(client, url)
                is_article = det.is_article_page(html) if html else False
                results[url] = {"is_article": is_article}

        tasks = [asyncio.create_task(worker(url)) for url in to_check]
        if tasks:
            for fut in asyncio.as_completed(tasks):
                await fut

    confirmed = [u for u, info in results.items() if info.get("is_article")]
    confirmed_count = len(confirmed)

    url_to_meta = {m["url"]: {"title": m.get("title"), "published_at": m.get("published_at")} for m in urls_meta}
    examples = []
    for u in confirmed[:5]:
        meta = url_to_meta.get(u, {})
        examples.append({"url": u, "title": meta.get("title"), "published_at": meta.get("published_at")})

    summary = {
        "total_before": total_before,
        "cheap_candidates": cheap_count,
        "checked": len(to_check),
        "confirmed_html": confirmed_count,
        "examples": examples,
    }

    OUT_JSON.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    OUT_SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"kun.uz: total={total_before}, cheap_candidates={cheap_count}, checked={len(to_check)}, confirmed={confirmed_count}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    asyncio.run(main())