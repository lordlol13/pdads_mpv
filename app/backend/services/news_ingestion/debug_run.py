from __future__ import annotations

import asyncio

from app.backend.core.config import settings
from app.backend.services.news_ingestion.global_fetcher import (
    fetch_global_news,
    fetch_newsapi,
    extract_article,
)
from app.backend.services.news_ingestion.regional_fetcher import fetch_regional_news
from app.backend.services.http_client import get_async_client


async def main() -> None:
    print("[debug_run] NEWS_API_KEY set:", bool(settings.NEWS_API_KEY and settings.NEWS_API_KEY.strip()))

    print("[debug_run] running fetch_newsapi (page_size=5)")
    client = await get_async_client()
    articles = await fetch_newsapi(client, "AI", page_size=5, api_key=(settings.NEWS_API_KEY or None))
    print("[debug_run] newsapi candidate count:", len(articles))
    for i, art in enumerate(articles[:10], start=1):
        url = art.get("url")
        print(f"[debug_run] candidate {i}: {url}")
        if url:
            text = await extract_article(client, url, verbose=True)
            print(f"[debug_run] extracted length for candidate {i}:", len(text) if text else 0)

    print("[debug_run] running fetch_regional_news for daryo.uz (limit=5)")
    regional_items = await fetch_regional_news(sources=["https://daryo.uz/news"], per_source_limit=5, verbose=True)
    print("[debug_run] regional returned:", len(regional_items))
    if regional_items:
        print("[debug_run] sample regional titles:", [a.get("title") for a in regional_items[:3]])


if __name__ == "__main__":
    asyncio.run(main())
