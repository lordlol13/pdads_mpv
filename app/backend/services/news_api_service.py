from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import json
import logging
import re
from typing import Any
from xml.etree import ElementTree as ET

import httpx
from openai import AsyncOpenAI

from app.backend.core.config import settings
from app.backend.services.orchestrator_service import build_cache_key, get_or_set_json

NEWS_API_URL = "https://newsapi.org/v2/everything"
logger = logging.getLogger(__name__)
_GROQ_BACKOFF_UNTIL: datetime | None = None

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


def _build_interest_classifier_client() -> tuple[AsyncOpenAI | None, str | None]:
    global _GROQ_BACKOFF_UNTIL

    if not settings.GROQ_API_KEY:
        return None, None

    if _GROQ_BACKOFF_UNTIL and datetime.now(timezone.utc) < _GROQ_BACKOFF_UNTIL:
        return None, None

    return (
        AsyncOpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1"),
        settings.GROQ_MODEL,
    )


def _mark_groq_backoff_if_needed(exc: Exception) -> None:
    global _GROQ_BACKOFF_UNTIL

    message = str(exc).lower()
    if "rate limit" not in message and "429" not in message and "rate_limit" not in message:
        return

    _GROQ_BACKOFF_UNTIL = datetime.now(timezone.utc) + timedelta(minutes=10)


async def _classify_interest_topics(topics: list[str]) -> list[str]:
    normalized_topics = _normalize_topics(topics)
    if not normalized_topics:
        return ["general"]

    if "general" in normalized_topics and len(normalized_topics) == 1:
        return ["general"]

    client, model_name = _build_interest_classifier_client()
    if client is None or not model_name:
        return normalized_topics

    try:
        response = await client.chat.completions.create(
            model=model_name,
            temperature=0.1,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You classify user interests for news ranking. "
                        "Return strict JSON: {\"query_terms\": string[], \"strict_topics\": string[]}. "
                        "query_terms: 4-10 expanded search phrases for NewsAPI; "
                        "strict_topics: 2-8 canonical topics for strict filtering. "
                        "Do not add topics that are not present in the original interests."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "interests": normalized_topics,
                            "language": "ru",
                            "goal": "pick relevant newsapi news",
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")

        strict_topics = payload.get("strict_topics") if isinstance(payload, dict) else []
        query_terms = payload.get("query_terms") if isinstance(payload, dict) else []

        combined: list[str] = []
        seen: set[str] = set()
        for raw_value in [*(strict_topics or []), *(query_terms or [])]:
            value = _normalize_topic_value(str(raw_value))
            if not value or value in seen:
                continue
            seen.add(value)
            combined.append(value)

        if combined:
            return combined[:12]
    except Exception as exc:
        _mark_groq_backoff_if_needed(exc)
        logger.warning("interest classification fallback triggered: %s", exc)

    return normalized_topics


async def _classify_interest_topics_cached(topics: list[str]) -> list[str]:
    normalized_topics = _normalize_topics(topics)
    if not normalized_topics:
        return ["general"]
    if not settings.GROQ_API_KEY:
        return normalized_topics

    cache_key = build_cache_key(
        "newsapi:interest-classifier",
        {
            "topics": normalized_topics,
            "model": settings.GROQ_MODEL,
            "provider": "groq",
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

    client, model_name = _build_interest_classifier_client()
    if client is None or not model_name:
        return newsapi_articles[:max_items]

    sampled = newsapi_articles[: min(len(newsapi_articles), 30)]
    compact_articles = []
    for idx, article in enumerate(sampled):
        compact_articles.append(
            {
                "idx": idx,
                "title": str(article.get("title") or "")[:240],
                "description": str(article.get("description") or "")[:280],
                "content": str(article.get("content") or "")[:360],
            }
        )

    try:
        response = await client.chat.completions.create(
            model=model_name,
            temperature=0.0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You rank article relevance for a user profile. Return strict JSON as "
                        "{\"selected_indices\": number[]}. Select only truly relevant articles "
                        "for the provided user interests."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "topics": topics,
                            "limit": int(max_items),
                            "articles": compact_articles,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        payload = json.loads(response.choices[0].message.content or "{}")
        selected_indices = payload.get("selected_indices") if isinstance(payload, dict) else []

        selected: list[dict[str, Any]] = []
        seen_idx: set[int] = set()
        for raw_idx in selected_indices or []:
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            if idx < 0 or idx >= len(sampled) or idx in seen_idx:
                continue
            seen_idx.add(idx)
            selected.append(sampled[idx])
            if len(selected) >= max_items:
                break

        if selected:
            for idx, article in enumerate(sampled):
                if idx in seen_idx:
                    continue
                selected.append(article)
                if len(selected) >= max_items:
                    break
            return selected[:max_items]
    except Exception as exc:
        _mark_groq_backoff_if_needed(exc)
        logger.warning("news selection fallback triggered: %s", exc)

    return sampled[:max_items]


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
                "urlToImage": None,
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

    def _sort_key(item: dict[str, Any]) -> tuple[int, float]:
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
    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
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

    async with httpx.AsyncClient(timeout=30.0) as client:
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
