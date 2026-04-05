from __future__ import annotations

from typing import Any

import requests

from app.backend.core.config import settings
from app.backend.services.orchestrator_service import build_cache_key, get_or_set_json

NEWS_API_URL = "https://newsapi.org/v2/everything"


async def fetch_media_urls(topic: str, limit: int = 5) -> list[str]:
    if not topic:
        topic = "news"

    async def _fetch() -> dict[str, Any]:
        if not settings.NEWS_API_KEY:
            return {"articles": []}

        response = requests.get(
            NEWS_API_URL,
            params={
                "q": topic,
                "pageSize": max(10, limit * 2),
                "sortBy": "relevancy",
                "language": "en",
                "apiKey": settings.NEWS_API_KEY,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    cache_key = build_cache_key("newsapi:media", {"topic": topic, "limit": limit})
    payload = await get_or_set_json(cache_key, ttl_seconds=1800, fetcher=_fetch)

    urls: list[str] = []
    for article in payload.get("articles") or []:
        image_url = article.get("urlToImage")
        if image_url and image_url not in urls:
            urls.append(image_url)
        if len(urls) >= limit:
            break

    if urls:
        return urls

    fallback_topic = topic.replace(" ", ",")
    return [f"https://source.unsplash.com/featured/1280x720/?{fallback_topic}&sig={idx}" for idx in range(limit)]
