#!/usr/bin/env python3
import asyncio
import httpx
from app.backend.services.news_api_service import _parse_rss_payload

async def fetch_and_parse(url: str, name: str, priority: int = 100):
    async with httpx.AsyncClient(timeout=15.0) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            text = resp.text
        except Exception as e:
            print(f"[ERROR] {name} ({url}): {e}")
            return []

    items = _parse_rss_payload(text, name, priority)
    return items

async def main():
    feeds = [
        ("Gazeta.uz (ru)", "https://www.gazeta.uz/ru/rss"),
        ("Daryo (rss)", "https://daryo.uz/rss"),
    ]

    for name, url in feeds:
        print(f"\nFetching {name}: {url}")
        items = await fetch_and_parse(url, name)
        print(f"Found {len(items)} items in {name}")
        for i, item in enumerate(items[:8], start=1):
            title = item.get("title") or "(no title)"
            link = item.get("url") or item.get("source_url") or "(no url)"
            pub = item.get("publishedAt") or "(no date)"
            print(f" {i}. {title} — {link} — {pub}")

if __name__ == '__main__':
    asyncio.run(main())
