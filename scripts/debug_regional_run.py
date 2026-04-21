from __future__ import annotations

import asyncio

from app.backend.services.news_ingestion.regional_fetcher import fetch_regional_news


async def main():
    sources = ["https://daryo.uz", "https://kun.uz"]
    print("Starting regional debug run for:", sources)
    articles = await fetch_regional_news(sources=sources, per_source_limit=2, verbose=True)
    print(f"REGIONAL_RESULT: {len(articles)} articles")
    for a in articles:
        print("-", a.get("source_url"), "|", (a.get("title") or "")[:120])


if __name__ == '__main__':
    asyncio.run(main())
