#!/usr/bin/env python3
import asyncio
from app.backend.services.news_api_service import _scrape_site_for_articles

async def main():
    items = await _scrape_site_for_articles("https://daryo.uz/", "Daryo (scrape)", 100, 10)
    print(f"Found {len(items)} scraped items")
    for i, it in enumerate(items[:10], 1):
        print(f"{i}. {it.get('title')[:140]} — {it.get('url')}")

if __name__ == '__main__':
    asyncio.run(main())
