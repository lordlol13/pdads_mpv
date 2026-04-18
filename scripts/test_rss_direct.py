#!/usr/bin/env python3
import asyncio
from app.backend.services.news_api_service import _fetch_rss_whitelist_articles

async def main():
    items = await _fetch_rss_whitelist_articles(['general'], ['UZ'], limit=20)
    print(f"Fetched {len(items)} RSS/scraped items for UZ")
    for i, it in enumerate(items[:20], 1):
        src = it.get('url') or '(no url)'
        print(f"{i}. {it.get('title')[:120]} — {src}")

if __name__ == '__main__':
    asyncio.run(main())
