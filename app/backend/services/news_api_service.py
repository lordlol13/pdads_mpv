from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import requests

from app.backend.core.config import settings
from app.backend.services.orchestrator_service import build_cache_key, get_or_set_json

NEWS_API_URL = "https://newsapi.org/v2/everything"


def _normalize_article(article: dict[str, Any]) -> dict[str, Any]:
    source = article.get("source") or {}
    title = (article.get("title") or "").strip()
    description = (article.get("description") or "").strip()
    content = (article.get("content") or "").strip()
    raw_text = "\n\n".join(part for part in [description, content] if part)

    return {
        "title": title or "Untitled",
        "raw_text": raw_text,
        "source_url": article.get("url"),
        "category": "general",
        "region": source.get("name") or "global",
        "is_urgent": False,
        "image_url": article.get("urlToImage"),
        "published_at": article.get("publishedAt"),
    }


def _parse_newsapi_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _prioritize_recent_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    now_utc = datetime.now(timezone.utc)
    recent_border = now_utc - timedelta(hours=settings.NEWS_PRIORITY_MAX_AGE_HOURS)

    def _sort_key(item: dict[str, Any]) -> tuple[int, float]:
        published_at = _parse_newsapi_datetime(item.get("publishedAt"))
        if published_at is None:
            return (1, 0.0)
        # 0 means priority bucket (fresh <= 24h), 1 means older bucket (but still <= 7 days).
        freshness_bucket = 0 if published_at >= recent_border else 1
        return (freshness_bucket, -published_at.timestamp())

    return sorted(articles, key=_sort_key)


async def fetch_articles_for_topics(topics: list[str], page_size: int) -> list[dict[str, Any]]:
    if not settings.NEWS_API_KEY:
        return []

    unique_topics = [topic for topic in dict.fromkeys([t.strip().lower() for t in topics if t.strip()])]
    if not unique_topics:
        unique_topics = ["uzbekistan"]

    async def _fetch() -> dict[str, Any]:
        query = " OR ".join(unique_topics[:5])
        now_utc = datetime.now(timezone.utc)
        max_age_border = now_utc - timedelta(days=settings.NEWS_MAX_AGE_DAYS)
        response = requests.get(
            NEWS_API_URL,
            params={
                "q": query,
                "pageSize": page_size,
                "sortBy": "publishedAt",
                "language": "en",
                "from": max_age_border.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "apiKey": settings.NEWS_API_KEY,
            },
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    cache_key = build_cache_key("newsapi:everything", {"topics": unique_topics, "page_size": page_size})
    payload = await get_or_set_json(cache_key, ttl_seconds=900, fetcher=_fetch)

    articles = _prioritize_recent_articles(payload.get("articles") or [])
    return [_normalize_article(article) for article in articles if article.get("title")]
