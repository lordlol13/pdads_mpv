"""Собрать и показать по 5 примеров с каждого источника (title, url, image).

Скрипт подменяет `create_raw_news`, чтобы не писать в БД, и вызывает
`feed_fetcher.ingest_many` с малыми лимитами. Собранные элементы выводятся
группами по доменам.
"""
from __future__ import annotations

import asyncio
import sys
import json
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

from app.backend.services import feed_fetcher, ingestion_service


SAMPLE_LIMIT_PER_DOMAIN = 5

collected: dict[str, list[dict]] = defaultdict(list)


async def _fake_create_raw_news(session, payload):
    src = payload.get("source_url") or ""
    domain = urlparse(src).netloc.lower().removeprefix("www.")
    item = {
        "title": (payload.get("title") or "").strip(),
        "source_url": src,
        "image_url": payload.get("image_url"),
        "excerpt": (payload.get("raw_text") or "").strip().replace("\n", " ")[:400],
    }
    if len(collected[domain]) < SAMPLE_LIMIT_PER_DOMAIN:
        collected[domain].append(item)
    return {"id": None, **payload}


async def main():
    # Monkeypatch DB writer to avoid mutations during dry-run
    ingestion_service.create_raw_news = _fake_create_raw_news
    try:
        feed_fetcher.create_raw_news = _fake_create_raw_news
    except Exception:
        pass

    per_rss_limit = 5
    per_site_limit = 5

    print("Starting sample run (up to 5 items per domain)...")
    summary = await feed_fetcher.ingest_many(None, per_rss_limit=per_rss_limit, per_site_limit=per_site_limit)

    # Ensure we show known default domains even if empty
    defaults = [
        "https://gazeta.uz/ru/rss",
        "https://daryo.uz/rss",
        "https://uz24.uz",
        "https://uznews.uz",
        "https://kun.uz",
        "https://podrobno.uz",
    ]
    domains = set(collected.keys())
    for u in defaults:
        domains.add(urlparse(u).netloc.lower().removeprefix("www."))

    for domain in sorted(domains):
        items = collected.get(domain, [])
        print(f"\n=== {domain} — found {len(items)} ===\n")
        for i, it in enumerate(items, start=1):
            print(f"{i}. {it['title']}")
            print(f"   URL: {it['source_url']}")
            print(f"   IMAGE: {it['image_url']}")
            if it.get("excerpt"):
                ex = it["excerpt"]
                print("   Excerpt:", (ex[:300] + "...") if len(ex) > 300 else ex)
            print()

    print("Run summary:", summary)

    # save results to JSON for review
    out_path = Path(__file__).resolve().parent / "parsed_samples.json"
    with out_path.open("w", encoding="utf8") as fh:
        json.dump({k: v for k, v in collected.items()}, fh, ensure_ascii=False, indent=2)
    print(f"Saved parsed samples to: {out_path}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
