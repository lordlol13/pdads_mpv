from __future__ import annotations

from typing import Any

import httpx

from app.backend.core.config import settings
from app.backend.services.orchestrator_service import build_cache_key, get_or_set_json

NEWS_API_URL = "https://newsapi.org/v2/everything"
YOUTUBE_SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"

COUNTRY_VIDEO_HINTS: dict[str, list[str]] = {
    "UZ": ["UzNews", "Kun.uz", "Gazeta.uz"],
    "RU": ["Россия 24", "РБК", "РИА Новости"],
    "KZ": ["Tengri News", "Khabar 24"],
}

COUNTRY_LANGUAGE_HINTS: dict[str, str] = {
    "UZ": "uz",
    "RU": "ru",
    "KZ": "ru",
    "US": "en",
}

MUSIC_VIDEO_TERMS = (
    "official music video",
    "lyrics",
    "karaoke",
    "remix",
    "live concert",
    "audio",
)


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
    try:
        payload = await get_or_set_json(cache_key, ttl_seconds=1800, fetcher=_fetch)
    except httpx.HTTPError:
        payload = {"articles": []}

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
    return values


async def fetch_video_urls(
    topic: str,
    profession: str | None,
    geo: str | None,
    limit: int = 3,
    country_code: str | None = None,
) -> list[str]:
    normalized_country = (country_code or "").strip().upper()
    country_hints = COUNTRY_VIDEO_HINTS.get(normalized_country, [])
    query_parts = [topic.strip() if topic else "news"]
    if profession:
        query_parts.append(profession.strip())
    if geo:
        query_parts.append(geo.strip())
    if country_hints:
        query_parts.extend(country_hints[:2])
    query = " ".join(part for part in query_parts if part)
    query += " latest news report analysis -song -music -lyrics -karaoke -remix -clip"

    region_code = normalized_country if len(normalized_country) == 2 else settings.YOUTUBE_REGION_CODE
    relevance_language = COUNTRY_LANGUAGE_HINTS.get(normalized_country, "en")

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
                    "regionCode": region_code,
                    "relevanceLanguage": relevance_language,
                    "videoCategoryId": "25",
                    "videoEmbeddable": "true",
                    "videoSyndicated": "true",
                    "order": "date",
                    "safeSearch": "moderate",
                    "key": settings.YOUTUBE_API_KEY,
                },
            )
        response.raise_for_status()
        return response.json()

    cache_key = build_cache_key(
        "youtube:videos",
        {"query": query, "limit": limit, "region": region_code},
    )
    try:
        payload = await get_or_set_json(cache_key, ttl_seconds=1800, fetcher=_fetch)
    except httpx.HTTPError:
        payload = {"items": []}

    videos: list[str] = []
    for item in payload.get("items") or []:
        video_id = (((item.get("id") or {}).get("videoId")) or "").strip()
        if not video_id:
            continue

        snippet_title = str((item.get("snippet") or {}).get("title") or "").strip().lower()
        if any(term in snippet_title for term in MUSIC_VIDEO_TERMS):
            continue

        video_url = f"https://www.youtube.com/watch?v={video_id}"
        if video_url not in videos:
            videos.append(video_url)
        if len(videos) >= limit:
            break

    if videos:
        return videos

    return _video_template_urls()[:limit]
