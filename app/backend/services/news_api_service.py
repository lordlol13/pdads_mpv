from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import re
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse
from xml.etree import ElementTree as ET

import httpx
from app.backend.services.http_client import get_async_client

from app.backend.core.config import settings
from app.backend.core.logging import ContextLogger
from app.backend.services.orchestrator_service import build_cache_key, get_or_set_json
from app.backend.services.recommender_service import cosine_similarity, text_to_embedding
from app.backend.services.resilience_service import (
    check_rate_limit,
    retry_async,
    _news_api_limiter,
)

NEWS_API_URL = "https://newsapi.org/v2/everything"
logger = ContextLogger(__name__)

RSS_SOURCE_WHITELIST: dict[str, list[dict[str, Any]]] = {
    "global": [
        {"name": "BBC World", "url": "http://feeds.bbci.co.uk/news/world/rss.xml", "priority": 120},
        {"name": "BBC Technology", "url": "http://feeds.bbci.co.uk/news/technology/rss.xml", "priority": 118},
        {"name": "CNN World", "url": "http://rss.cnn.com/rss/edition_world.rss", "priority": 116},
        {"name": "CNN Top", "url": "http://rss.cnn.com/rss/edition.rss", "priority": 114},
        {"name": "Reuters World", "url": "https://feeds.reuters.com/Reuters/worldNews", "priority": 112},
        {"name": "DW World", "url": "https://rss.dw.com/rdf/rss-en-world", "priority": 110},
    ],
    "uz": [
        {"name": "Kun.uz", "url": "https://kun.uz/news/rss", "priority": 106},
        {"name": "Gazeta.uz", "url": "https://www.gazeta.uz/rss/", "priority": 104},
        {"name": "Daryo", "url": "https://daryo.uz/feed", "priority": 102},
    ],
}

COUNTRY_NEWS_DOMAINS: dict[str, list[str]] = {
    "UZ": ["kun.uz", "gazeta.uz", "daryo.uz", "uznews.uz"],
    "RU": ["ria.ru", "rbc.ru", "lenta.ru", "vesti.ru"],
    "KZ": ["tengrinews.kz", "inform.kz"],
    "US": ["apnews.com", "reuters.com", "cnn.com"],
}

TOPIC_QUERY_ALIASES: dict[str, list[str]] = {
    "cs": ["counter-strike", "counter strike", "counter-strike 2", "cs2", "esports"],
    "cs2": ["counter-strike 2", "counter strike 2", "cs2", "esports"],
    "dota": ["dota 2", "dota2", "the international", "esports"],
    "dota2": ["dota 2", "dota2", "the international", "esports"],
    "valorant": ["valorant", "vct", "esports"],
}


def _normalize_topic_value(topic: str) -> str:
    return re.sub(r"\s+", " ", str(topic or "").strip().lower())


def _normalize_topics(topics: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for topic in topics:
        value = _normalize_topic_value(topic)
        if not value or value in seen:
            continue
        seen.add(value)
        result.append(value)
    return result


def _topic_variants(topic: str) -> list[str]:
    normalized = _normalize_topic_value(topic)
    if not normalized:
        return []

    aliases = TOPIC_QUERY_ALIASES.get(normalized, [])
    if normalized == "cs":
        raw = aliases
    else:
        raw = [*aliases, normalized]

    variants: list[str] = []
    seen: set[str] = set()
    for value in raw:
        v = _normalize_topic_value(value)
        if not v or v in seen:
            continue
        seen.add(v)
        variants.append(v)
    return variants


def _expand_topics_for_query(topics: list[str]) -> list[str]:
    normalized_topics = _normalize_topics(topics)
    specific_topics = [topic for topic in normalized_topics if topic != "general"]

    if not specific_topics:
        return ["general news"]

    expanded: list[str] = []
    seen: set[str] = set()
    for topic in specific_topics:
        for variant in _topic_variants(topic):
            if len(variant) <= 2:
                continue
            if variant in seen:
                continue
            seen.add(variant)
            expanded.append(variant)

    return expanded or specific_topics


def _merge_topics_preserving_order(primary: list[str], secondary: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for raw in [*primary, *secondary]:
        value = _normalize_topic_value(raw)
        if not value or value in seen:
            continue
        seen.add(value)
        merged.append(value)
    return merged


async def _classify_interest_topics(topics: list[str]) -> list[str]:
    normalized_topics = _normalize_topics(topics)
    if not normalized_topics:
        return ["general"]

    if "general" in normalized_topics and len(normalized_topics) == 1:
        return ["general"]

    expanded: list[str] = []
    seen: set[str] = set()
    for topic in normalized_topics:
        for variant in _topic_variants(topic):
            if variant in seen:
                continue
            seen.add(variant)
            expanded.append(variant)

    return expanded or normalized_topics


async def _classify_interest_topics_cached(topics: list[str]) -> list[str]:
    normalized_topics = _normalize_topics(topics)
    if not normalized_topics:
        return ["general"]

    cache_key = build_cache_key(
        "newsapi:interest-classifier",
        {
            "topics": normalized_topics,
            "model": "embedding-heuristic-v1",
            "provider": "local",
        },
    )

    async def _fetch() -> dict[str, Any]:
        classified = await _classify_interest_topics(normalized_topics)
        return {"topics": classified}

    payload = await get_or_set_json(cache_key, ttl_seconds=3600, fetcher=_fetch)
    classified_topics = payload.get("topics") if isinstance(payload, dict) else []
    if isinstance(classified_topics, list):
        result = _normalize_topics([str(value) for value in classified_topics])
        if result:
            return result

    return normalized_topics


async def _ai_select_newsapi_articles(
    topics: list[str],
    newsapi_articles: list[dict[str, Any]],
    max_items: int,
) -> list[dict[str, Any]]:
    if not newsapi_articles:
        return []

    sampled = newsapi_articles[: min(len(newsapi_articles), 30)]
    topic_text = " ".join(_normalize_topics(topics)) or "general news"
    topic_vector = text_to_embedding(topic_text)

    scored: list[tuple[float, dict[str, Any]]] = []
    for article in sampled:
        article_text = " ".join(
            [
                str(article.get("title") or ""),
                str(article.get("description") or ""),
                str(article.get("content") or ""),
                str((article.get("source") or {}).get("name") or ""),
            ]
        )
        article_vector = text_to_embedding(article_text)
        similarity = cosine_similarity(topic_vector, article_vector)
        topical_match = 1.0 if _article_matches_topics(article, topics) else 0.0
        source_priority = float(article.get("_source_priority") or 0) / 100.0
        freshness_boost = 0.0
        published_at = _parse_newsapi_datetime(article.get("publishedAt"))
        if published_at is not None:
            age_hours = max(0.0, (datetime.now(timezone.utc) - published_at).total_seconds() / 3600.0)
            freshness_boost = max(0.0, 1.0 - min(age_hours / 96.0, 1.0))

        score = (similarity * 1.8) + (topical_match * 1.2) + source_priority + freshness_boost
        scored.append((score, article))

    scored.sort(key=lambda item: item[0], reverse=True)
    selected = [article for score, article in scored[:max_items] if score >= 0.15]
    return selected or sampled[:max_items]


def _normalize_article(article: dict[str, Any]) -> dict[str, Any]:
    source = article.get("source") or {}
    title = (article.get("title") or "").strip()
    description = (article.get("description") or "").strip()
    content = (article.get("content") or "").strip()
    raw_text = "\n\n".join(part for part in [description, content] if part)

    return {
        "title": title or "Untitled",
        "raw_text": raw_text,
        "source_url": _unwrap_redirect_url(str(article.get("url") or "").strip()),
        "category": "general",
        "region": source.get("name") or "global",
        "is_urgent": False,
        "image_url": article.get("urlToImage"),
        "published_at": article.get("publishedAt"),
    }


def _unwrap_redirect_url(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return ""

    current = value
    for _ in range(3):
        parsed = urlparse(current)
        query = parse_qs(parsed.query)
        next_url = ""
        for key in ("url", "u", "continue", "redirect", "redirect_uri", "dest", "destination", "r"):
            candidates = query.get(key)
            if not candidates:
                continue
            candidate = unquote(str(candidates[0] or "").strip())
            if candidate.lower().startswith(("http://", "https://")):
                next_url = candidate
                break

        if not next_url:
            break
        current = next_url

    return current


def _tag_name(tag: str) -> str:
    return str(tag).split("}")[-1].lower()


def _extract_first_text(node: ET.Element, names: set[str]) -> str:
    for child in node.iter():
        if child is node:
            continue
        if _tag_name(child.tag) in names:
            value = (child.text or "").strip()
            if value:
                return value
    return ""


def _extract_link(node: ET.Element) -> str:
    for child in node.iter():
        if child is node:
            continue
        if _tag_name(child.tag) != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        if href:
            return href
        text_value = (child.text or "").strip()
        if text_value:
            return text_value
    return ""


def _extract_image_url(node: ET.Element) -> str | None:
    for child in node.iter():
        if child is node:
            continue

        tag = _tag_name(child.tag)
        attrs = {str(k or "").lower(): str(v or "").strip() for k, v in child.attrib.items()}

        if tag in {"content", "thumbnail"}:
            # media:content and media:thumbnail usually expose image URL in url attr.
            media_url = attrs.get("url") or attrs.get("href")
            if media_url and media_url.lower().startswith(("http://", "https://")):
                return media_url

        if tag == "enclosure":
            media_url = attrs.get("url") or attrs.get("href")
            media_type = attrs.get("type", "").lower()
            if media_url and media_url.lower().startswith(("http://", "https://")):
                if ("image/" in media_type) or media_url.lower().endswith((".jpg", ".jpeg", ".png", ".webp", ".avif")):
                    return media_url

        if tag in {"image", "url"}:
            text_value = (child.text or "").strip()
            if text_value.lower().startswith(("http://", "https://")):
                lowered = text_value.lower()
                if lowered.endswith((".jpg", ".jpeg", ".png", ".webp", ".avif")) or "image" in lowered:
                    return text_value

    return None


def _to_newsapi_timestamp(raw_value: str | None) -> str | None:
    if not raw_value:
        return None

    value = raw_value.strip()
    if not value:
        return None

    for parser in (
        lambda: datetime.fromisoformat(value.replace("Z", "+00:00")),
        lambda: parsedate_to_datetime(value),
    ):
        try:
            parsed = parser()
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        except Exception:
            continue

    return None


def _article_matches_topics(article: dict[str, Any], topics: list[str]) -> bool:
    normalized_topics = _normalize_topics(topics)
    specific_topics = [topic for topic in normalized_topics if topic != "general"]

    if not specific_topics:
        return True

    haystack = " ".join(
        [
            str(article.get("title") or "").lower(),
            str(article.get("description") or "").lower(),
            str(article.get("content") or "").lower(),
        ]
    )

    for topic in specific_topics:
        for variant in _topic_variants(topic):
            if len(variant) <= 2:
                if re.search(rf"(?<![a-z0-9]){re.escape(variant)}(?![a-z0-9])", haystack):
                    return True
                continue

            if variant in haystack:
                return True

    return False


def _rss_sources_for_country_codes(country_codes: list[str] | None) -> list[dict[str, Any]]:
    normalized_codes = {code.strip().upper() for code in (country_codes or []) if code and code.strip()}

    selected = list(RSS_SOURCE_WHITELIST["global"])
    # Uzbekistan sources are explicitly prioritized for this product's target audience.
    selected.extend(RSS_SOURCE_WHITELIST["uz"])

    deduped: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for source in selected:
        url = str(source.get("url") or "").strip().lower()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        source_copy = dict(source)
        if "UZ" in normalized_codes and source in RSS_SOURCE_WHITELIST["uz"]:
            source_copy["priority"] = int(source_copy.get("priority") or 0) + 4
        deduped.append(source_copy)

    return deduped


def _parse_rss_payload(payload: str, source_name: str, source_priority: int) -> list[dict[str, Any]]:
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return []

    items: list[dict[str, Any]] = []
    for node in root.iter():
        if _tag_name(node.tag) not in {"item", "entry"}:
            continue

        title = _extract_first_text(node, {"title"})
        link = _extract_link(node)
        description = _extract_first_text(node, {"description", "summary", "content", "encoded"})
        image_url = _extract_image_url(node)
        published_raw = _extract_first_text(node, {"pubdate", "published", "updated", "date"})
        published_at = _to_newsapi_timestamp(published_raw)

        if not title or not link:
            continue

        items.append(
            {
                "source": {"name": source_name},
                "title": title,
                "description": description,
                "content": description,
                "url": link,
                "urlToImage": image_url,
                "publishedAt": published_at,
                "_source_priority": source_priority,
            }
        )

    return items


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

    def _sort_key(item: dict[str, Any]) -> tuple[int, int, float]:
        published_at = _parse_newsapi_datetime(item.get("publishedAt"))
        source_priority = -int(item.get("_source_priority") or 0)
        if published_at is None:
            return (source_priority, 1, 0.0)
        # 0 means priority bucket (fresh <= 24h), 1 means older bucket (but still <= 7 days).
        freshness_bucket = 0 if published_at >= recent_border else 1
        return (source_priority, freshness_bucket, -published_at.timestamp())

    return sorted(articles, key=_sort_key)


def _preferred_domains_for_countries(country_codes: list[str] | None) -> list[str]:
    if not country_codes:
        return []

    unique_codes = [code.strip().upper() for code in country_codes if code and code.strip()]
    domains: list[str] = []
    for code in unique_codes:
        for domain in COUNTRY_NEWS_DOMAINS.get(code, []):
            if domain not in domains:
                domains.append(domain)
    return domains


def _dedupe_articles_by_url_or_title(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen_keys: set[str] = set()
    result: list[dict[str, Any]] = []

    for article in articles:
        url = str(article.get("url") or "").strip().lower()
        title = str(article.get("title") or "").strip().lower()
        dedupe_key = url or title
        if not dedupe_key or dedupe_key in seen_keys:
            continue
        seen_keys.add(dedupe_key)
        result.append(article)

    return result


async def _fetch_rss_whitelist_articles(
    topics: list[str],
    country_codes: list[str] | None,
    limit: int,
) -> list[dict[str, Any]]:
    sources = _rss_sources_for_country_codes(country_codes)
    if not sources:
        return []

    items: list[dict[str, Any]] = []
    client = await get_async_client()
    for source in sources:
        source_name = str(source.get("name") or "RSS")
        source_url = str(source.get("url") or "").strip()
        source_priority = int(source.get("priority") or 0)
        if not source_url:
            continue

        try:
            response = await client.get(source_url, params={})
            response.raise_for_status()
        except httpx.HTTPError:
            continue

        response_text = getattr(response, "text", "")
        if not isinstance(response_text, str) or not response_text.strip():
            continue

        parsed = _parse_rss_payload(response_text, source_name, source_priority)
        for article in parsed:
            if _article_matches_topics(article, topics):
                items.append(article)

        if len(items) >= limit * 2:
            break

    deduped = _dedupe_articles_by_url_or_title(items)
    return _prioritize_recent_articles(deduped)[:limit]


async def _fetch_newsapi_articles(
    topics: list[str],
    page_size: int,
    preferred_domains: list[str],
) -> list[dict[str, Any]]:
    if not settings.NEWS_API_KEY:
        return []

    # Rate limit check
    allowed = await check_rate_limit(
        f"newsapi:topics:{','.join(topics[:3])}",
        limiter=_news_api_limiter,
        limit=settings.NEWS_API_RATE_LIMIT_PER_MINUTE,
        window_seconds=60,
    )
    if not allowed:
        logger.warning(f"News API rate limit exceeded for topics: {topics}")
        if settings.NEWS_API_FALLBACK_TO_RSS:
            logger.info("Falling back to RSS sources")
            return []
        return []

    query_terms = _expand_topics_for_query(topics)
    query = " OR ".join(
        [f'"{term}"' if (" " in term or "-" in term) else term for term in query_terms[:8]]
    )
    if not query:
        query = "general news"
    now_utc = datetime.now(timezone.utc)
    max_age_border = now_utc - timedelta(days=settings.NEWS_MAX_AGE_DAYS)

    base_params = {
        "q": query,
        "sortBy": "publishedAt",
        "from": max_age_border.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "to": now_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "apiKey": settings.NEWS_API_KEY,
    }

    async def _make_requests():
        client = await get_async_client()
        if not preferred_domains:
            response = await client.get(
                NEWS_API_URL,
                params={
                    **base_params,
                    "pageSize": page_size,
                    "language": "en",
                },
            )
            response.raise_for_status()
            payload = response.json()
            for article in payload.get("articles") or []:
                article.setdefault("_source_priority", 50)
            return payload.get("articles") or []

        country_page_size = max(1, int(page_size * 0.6))
        global_page_size = max(1, page_size - country_page_size)
        preferred_domains_csv = ",".join(preferred_domains[:20])

        country_response = await client.get(
            NEWS_API_URL,
            params={
                **base_params,
                "pageSize": country_page_size,
                "domains": preferred_domains_csv,
            },
        )
        country_response.raise_for_status()
        country_payload = country_response.json()
        for article in country_payload.get("articles") or []:
            article.setdefault("_source_priority", 90)

        global_response = await client.get(
            NEWS_API_URL,
            params={
                **base_params,
                "pageSize": global_page_size,
                "language": "en",
                "excludeDomains": preferred_domains_csv,
            },
        )
        global_response.raise_for_status()
        global_payload = global_response.json()
        for article in global_payload.get("articles") or []:
            article.setdefault("_source_priority", 70)

        return _dedupe_articles_by_url_or_title(
            (country_payload.get("articles") or []) + (global_payload.get("articles") or [])
        )

    try:
        articles = await retry_async(
            _make_requests,
            max_attempts=settings.API_RETRY_MAX_ATTEMPTS,
            base_delay_seconds=settings.API_RETRY_BASE_DELAY_SECONDS,
            max_delay_seconds=settings.API_RETRY_MAX_DELAY_SECONDS,
            retry_on_exceptions=(httpx.HTTPError, Exception),
        )
        return articles
    except Exception as e:
        logger.error(f"News API fetch failed after retries: {e}")
        if settings.NEWS_API_FALLBACK_TO_RSS:
            logger.info("Falling back to RSS sources")
            return []
        raise


async def fetch_articles_for_topics(
    topics: list[str],
    page_size: int,
    country_codes: list[str] | None = None,
) -> list[dict[str, Any]]:
    unique_topics = [topic for topic in dict.fromkeys([t.strip().lower() for t in topics if t.strip()])]
    if not unique_topics:
        unique_topics = ["general"]

    classified_topics = await _classify_interest_topics_cached(unique_topics)
    if not classified_topics:
        classified_topics = unique_topics
    effective_topics = _merge_topics_preserving_order(unique_topics, classified_topics)
    if not effective_topics:
        effective_topics = unique_topics

    preferred_domains = _preferred_domains_for_countries(country_codes)

    async def _fetch() -> dict[str, Any]:
        rss_articles = await _fetch_rss_whitelist_articles(
            effective_topics,
            country_codes,
            limit=max(page_size * 2, 24),
        )

        try:
            newsapi_articles = await _fetch_newsapi_articles(
                effective_topics,
                page_size=max(page_size, 12),
                preferred_domains=preferred_domains,
            )
        except httpx.HTTPError:
            newsapi_articles = []

        newsapi_articles = [item for item in newsapi_articles if _article_matches_topics(item, effective_topics)]
        newsapi_articles = await _ai_select_newsapi_articles(
            effective_topics,
            newsapi_articles,
            max_items=max(page_size, 12),
        )

        merged_articles = _dedupe_articles_by_url_or_title(rss_articles + newsapi_articles)
        return {"articles": merged_articles}

    cache_key = build_cache_key(
        "newsapi:everything",
        {
            "topics": unique_topics,
            "classified_topics": classified_topics,
            "effective_topics": effective_topics,
            "page_size": page_size,
            "country_codes": [code.strip().upper() for code in (country_codes or []) if code and code.strip()],
            "domains": preferred_domains,
            "global_mix": bool(preferred_domains),
            "rss_whitelist": True,
        },
    )
    payload = await get_or_set_json(cache_key, ttl_seconds=900, fetcher=_fetch)

    articles = _prioritize_recent_articles(payload.get("articles") or [])
    return [_normalize_article(article) for article in articles if article.get("title")][:page_size]
