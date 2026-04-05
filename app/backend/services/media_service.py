from __future__ import annotations

from typing import Any

import httpx

from app.backend.core.config import settings
from app.backend.services.orchestrator_service import build_cache_key, get_or_set_json

NEWS_API_URL = "https://newsapi.org/v2/everything"
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"


async def fetch_media_urls(topic: str, limit: int = 5) -> list[str]:
    if not topic:
        topic = "news"

    async def _fetch() -> dict[str, Any]:
        if not settings.NEWS_API_KEY:
            return {"articles": []}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                NEWS_API_URL,
                params={
                    "q": topic,
                    "pageSize": max(10, limit * 2),
                    "sortBy": "relevancy",
                    "language": "en",
                    "apiKey": settings.NEWS_API_KEY,
                },
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


def _video_template_urls() -> list[str]:
    values = [item.strip() for item in settings.VIDEO_TEMPLATE_URLS.split(",") if item.strip()]
    return values or ["https://www.youtube.com/watch?v=dQw4w9WgXcQ"]


async def fetch_video_urls(topic: str, profession: str | None, geo: str | None, limit: int = 3) -> list[str]:
    query_parts = [topic.strip() if topic else "news"]
    if profession:
        query_parts.append(profession.strip())
    if geo:
        query_parts.append(geo.strip())
    query = " ".join(part for part in query_parts if part)

    async def _fetch() -> dict[str, Any]:
        if not settings.YOUTUBE_API_KEY:
            return {"items": []}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                YOUTUBE_SEARCH_URL,
                params={
                    "part": "snippet",
                    "q": query,
                    "type": "video",
                    "maxResults": max(5, limit),
                    "regionCode": settings.YOUTUBE_REGION_CODE,
                    "key": settings.YOUTUBE_API_KEY,
                },
            )
        response.raise_for_status()
        return response.json()

    cache_key = build_cache_key(
        "youtube:videos",
        {"query": query, "limit": limit, "region": settings.YOUTUBE_REGION_CODE},
    )
    payload = await get_or_set_json(cache_key, ttl_seconds=1800, fetcher=_fetch)

    videos: list[str] = []
    for item in payload.get("items") or []:
        video_id = (((item.get("id") or {}).get("videoId")) or "").strip()
        if not video_id:
            continue
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        if video_url not in videos:
            videos.append(video_url)
        if len(videos) >= limit:
            break

    if videos:
        return videos

    return _video_template_urls()[:limit]
