#!/usr/bin/env python3
import asyncio
from urllib.parse import urlparse

from app.backend.services.news_api_service import fetch_articles_for_topics

async def main():
    topics = ["general"]
    page_size = 5
    articles = await fetch_articles_for_topics(topics, page_size=page_size, country_codes=["UZ"])
    print(f"Total articles returned: {len(articles)}")

    uz_domains = {"uz24.uz", "uznews.uz", "kun.uz", "daryo.uz", "gazeta.uz", "podrobno.uz"}
    regional = []
    global_ = []

    for a in articles:
        src = str(a.get("source_url") or "")
        netloc = urlparse(src).netloc.lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]
        if netloc in uz_domains:
            regional.append((netloc, a))
        else:
            global_.append((netloc, a))

    print(f"Regional ({len(regional)}):")
    for netloc, art in regional:
        print(f"- {art.get('title')[:120]} ({netloc})")

    print(f"Global ({len(global_)}):")
    for netloc, art in global_:
        print(f"- {art.get('title')[:120]} ({netloc})")

if __name__ == '__main__':
    asyncio.run(main())
