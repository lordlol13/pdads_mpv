from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any
from urllib.parse import parse_qs, urlencode, unquote, urljoin, urlparse

import httpx

from app.backend.core.config import settings
from app.backend.services.orchestrator_service import build_cache_key, get_or_set_json

NEWS_API_URL = "https://newsapi.org/v2/everything"
GOOGLE_CSE_IMAGE_SEARCH_URL = "https://www.googleapis.com/customsearch/v1"
WIKIMEDIA_API_URL = "https://commons.wikimedia.org/w/api.php"
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

LOW_QUALITY_IMAGE_TERMS = (
    "thumbnail",
    "thumb",
    "small",
    "tiny",
    "preview",
    "sprite",
)

MIN_PUBLIC_IMAGE_WIDTH = 800
MIN_PUBLIC_IMAGE_HEIGHT = 450
MIN_PUBLIC_IMAGE_AREA = MIN_PUBLIC_IMAGE_WIDTH * MIN_PUBLIC_IMAGE_HEIGHT

NEWS_IMAGE_BLOCKLIST_TERMS = (
    "logo",
    "icon",
    "avatar",
    "sprite",
    "favicon",
    "banner",
    "adserver",
    "pixel",
    "nojs",
    "placeholder",
    "blank",
)

GENERIC_STOCK_IMAGE_TERMS = (
    "mountain",
    "nature",
    "landscape",
    "forest",
    "beach",
    "sunset",
    "wallpaper",
    "background",
    "abstract",
    "businesswoman",
    "businessman",
)

TOPIC_STOPWORDS = {
    "news",
    "latest",
    "today",
    "update",
    "report",
    "story",
    "world",
    "global",
    "general",
    "yangilik",
    "yangiliklar",
    "uzbek",
    "uzbekiston",
}

NON_IMAGE_FILE_SUFFIXES = (
    ".js",
    ".css",
    ".json",
    ".xml",
    ".txt",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".map",
)

CURATED_TOPIC_FALLBACK_IMAGES: dict[str, list[str]] = {
    "esports": [
        "https://images.unsplash.com/photo-1542751371-adc38448a05e?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1511512578047-dfb367046420?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1560253023-3ec5d502959f?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1511882150382-421056c89033?auto=format&fit=crop&w=1600&q=80",
    ],
    "f1": [
        "https://images.unsplash.com/photo-1503376780353-7e6692767b70?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1556804335-2fa563e93aae?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1489515217757-5fd1be406fef?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1471478331149-c72f17e33c73?auto=format&fit=crop&w=1600&q=80",
    ],
    "ai": [
        "https://images.unsplash.com/photo-1677442136019-21780ecad995?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1485827404703-89b55fcc595e?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1518770660439-4636190af475?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1526374965328-7f61d4dc18c5?auto=format&fit=crop&w=1600&q=80",
    ],
    "sports": [
        "https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1574629810360-7efbbe195018?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1494173853739-c21f58b16055?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1461897104016-0b3b00cc81ee?auto=format&fit=crop&w=1600&q=80",
    ],
    "general": [
        "https://images.unsplash.com/photo-1495020689067-958852a7765e?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1504711434969-e33886168f5c?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1488190211105-8b0e65b80b4e?auto=format&fit=crop&w=1600&q=80",
        "https://images.unsplash.com/photo-1454165804606-c3d57bc86b40?auto=format&fit=crop&w=1600&q=80",
    ],
}

TOPIC_FALLBACK_ALIASES: dict[str, str] = {
    "team spirit": "esports",
    "dota": "esports",
    "dota2": "esports",
    "cs": "esports",
    "cs2": "esports",
    "counter strike": "esports",
    "valorant": "esports",
    "esports": "esports",
    "f1": "f1",
    "formula": "f1",
    "ai": "ai",
    "technology": "ai",
    "sports": "sports",
}

TRACKING_QUERY_KEYS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
    "source",
}

IMAGE_ID_QUERY_KEYS = {
    "id",
    "img",
    "image",
    "photo",
    "media",
    "file",
    "filename",
    "name",
    "asset",
}


class _ImageCandidateParser(HTMLParser):
    def __init__(self, base_url: str | None):
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.candidates: list[str] = []
        self.context_by_url: dict[str, str] = {}

    def _add(self, raw_url: str | None, context: str | None = None) -> None:
        normalized = _normalize_candidate_url(raw_url, self.base_url)
        if normalized:
            self.candidates.append(normalized)
            context_value = str(context or "").strip()
            if context_value:
                self.context_by_url[normalized] = f"{self.context_by_url.get(normalized, '')} {context_value}".strip()

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_name = str(tag or "").lower()
        attrs_map = {str(k or "").lower(): str(v or "").strip() for k, v in attrs}

        if tag_name == "meta":
            marker = (
                attrs_map.get("property")
                or attrs_map.get("name")
                or attrs_map.get("itemprop")
                or ""
            ).strip().lower()
            if marker in {"og:image", "og:image:url", "twitter:image", "twitter:image:src", "image"}:
                context_parts = [
                    attrs_map.get("property", ""),
                    attrs_map.get("name", ""),
                    attrs_map.get("itemprop", ""),
                ]
                self._add(attrs_map.get("content"), " ".join(part for part in context_parts if part))
            return

        if tag_name == "img":
            image_context = " ".join(
                part
                for part in (
                    attrs_map.get("alt", ""),
                    attrs_map.get("title", ""),
                    attrs_map.get("aria-label", ""),
                    attrs_map.get("class", ""),
                    attrs_map.get("id", ""),
                )
                if part
            )
            for key in ("src", "data-src", "data-original", "data-lazy-src", "data-image"):
                value = attrs_map.get(key)
                if value:
                    self._add(value, image_context)
                    break

            srcset = attrs_map.get("srcset")
            if srcset:
                first_item = srcset.split(",")[0].strip().split(" ")[0].strip()
                self._add(first_item, image_context)
            return

        if tag_name == "link":
            rel = attrs_map.get("rel", "").lower()
            preload_as = attrs_map.get("as", "").lower()
            preload_type = attrs_map.get("type", "").lower()
            is_image_preload = "preload" in rel and (preload_as == "image" or preload_type.startswith("image/"))
            if "image_src" in rel or is_image_preload:
                self._add(attrs_map.get("href"), rel)


def _extract_dimension_hints(url: str) -> tuple[int | None, int | None]:
    value = str(url or "").strip().lower()
    if not value:
        return None, None

    parsed = urlparse(value)
    query = parse_qs(parsed.query)

    width: int | None = None
    height: int | None = None

    for key in ("w", "width", "imgw"):
        values = query.get(key)
        if not values:
            continue
        raw = str(values[0] or "").strip()
        if raw.isdigit():
            width = int(raw)
            break

    for key in ("h", "height", "imgh"):
        values = query.get(key)
        if not values:
            continue
        raw = str(values[0] or "").strip()
        if raw.isdigit():
            height = int(raw)
            break

    if width is None or height is None:
        match = re.search(r"(?<!\d)(\d{2,4})[xX](\d{2,4})(?!\d)", f"{parsed.path} {parsed.query}")
        if match:
            if width is None:
                width = int(match.group(1))
            if height is None:
                height = int(match.group(2))

    if width is None:
        path_match = re.search(r"/(?:standard|news|thumb|thumbnail)/(\d{2,4})/", parsed.path)
        if path_match:
            width = int(path_match.group(1))

    return width, height


def _upgrade_known_image_url_quality(url: str) -> str:
    value = str(url or "").strip()
    if not value:
        return value

    parsed = urlparse(value)
    host = parsed.netloc.lower()
    path = parsed.path
    query = parsed.query

    if "ichef.bbci.co.uk" in host:
        # BBC often provides low-res variants like /standard/240/ and /news/480/.
        path = re.sub(r"(/ace/standard/)(\d{2,4})(/)", lambda m: f"{m.group(1)}1024{m.group(3)}" if int(m.group(2)) < 720 else m.group(0), path)
        path = re.sub(r"(/news/)(\d{2,4})(/)", lambda m: f"{m.group(1)}1024{m.group(3)}" if int(m.group(2)) < 720 else m.group(0), path)

    return parsed._replace(path=path, query=query).geturl()


def _build_media_topic(topic: str) -> str:
    value = str(topic or "").strip()
    return value or "news"


def _normalize_candidate_url(raw_url: str | None, base_url: str | None = None) -> str | None:
    value = str(raw_url or "").strip()
    if not value:
        return None

    lowered = value.lower()
    if lowered.startswith("data:") or lowered.startswith("javascript:"):
        return None

    if value.startswith("//"):
        value = f"https:{value}"

    if base_url and not re.match(r"^https?://", value, flags=re.IGNORECASE):
        value = urljoin(base_url, value)

    if not re.match(r"^https?://", value, flags=re.IGNORECASE):
        return None

    return value


def _looks_like_news_photo(url: str) -> bool:
    candidate = str(url or "").strip().lower()
    if not candidate:
        return False

    parsed = urlparse(candidate)
    combined = f"{parsed.path} {parsed.query}"
    if any(term in combined for term in NEWS_IMAGE_BLOCKLIST_TERMS):
        return False

    if any(term in combined for term in LOW_QUALITY_IMAGE_TERMS):
        return False

    if parsed.path.endswith(".svg") or parsed.path.endswith(".ico") or parsed.path.endswith(".gif"):
        return False

    if parsed.path.endswith(NON_IMAGE_FILE_SUFFIXES):
        return False

    width_hint, height_hint = _extract_dimension_hints(candidate)
    if width_hint is not None and height_hint is not None:
        if width_hint < MIN_PUBLIC_IMAGE_WIDTH or height_hint < MIN_PUBLIC_IMAGE_HEIGHT:
            return False
        if width_hint * height_hint < MIN_PUBLIC_IMAGE_AREA:
            return False
    elif width_hint is not None and width_hint < MIN_PUBLIC_IMAGE_WIDTH:
        return False
    elif height_hint is not None and height_hint < MIN_PUBLIC_IMAGE_HEIGHT:
        return False

    for width_raw, height_raw in re.findall(r"(?<!\d)(\d{2,4})[xX](\d{2,4})(?!\d)", combined):
        width = int(width_raw)
        height = int(height_raw)
        if width < 360 or height < 220:
            return False

    return True


def _topic_tokens(topic: str) -> list[str]:
    parts = [part for part in re.split(r"[^\w]+", str(topic or "").lower()) if part]

    tokens: list[str] = []
    seen: set[str] = set()
    for part in parts:
        if len(part) < 3 or part.isdigit() or part in TOPIC_STOPWORDS:
            continue
        if part in seen:
            continue
        seen.add(part)
        tokens.append(part)

    max_ngram = min(3, len(tokens))
    for n in range(2, max_ngram + 1):
        for idx in range(0, len(tokens) - n + 1):
            phrase = " ".join(tokens[idx : idx + n]).strip()
            if len(phrase) < 6 or phrase in seen:
                continue
            seen.add(phrase)
            tokens.append(phrase)

    return tokens[:12]


def _is_generic_stock_candidate(url: str, context: str) -> bool:
    haystack = f"{url} {context}".lower()
    return any(term in haystack for term in GENERIC_STOCK_IMAGE_TERMS)


def _choose_fallback_bucket(topic: str) -> str:
    normalized = str(topic or "").strip().lower()
    if not normalized:
        return "general"

    for alias, bucket in TOPIC_FALLBACK_ALIASES.items():
        if alias in normalized:
            return bucket

    tokens = _topic_tokens(normalized)
    for token in tokens:
        bucket = TOPIC_FALLBACK_ALIASES.get(token)
        if bucket:
            return bucket

    return "general"


def _source_domain(url: str | None) -> str:
    if not url:
        return ""
    return urlparse(url).netloc.lower().removeprefix("www.")


def _unwrap_redirect_url(url: str | None) -> str | None:
    value = str(url or "").strip()
    if not value:
        return None

    current = value
    for _ in range(3):
        parsed = urlparse(current)
        query = parse_qs(parsed.query)
        next_url = ""
        for key in ("url", "u", "continue", "redirect", "redirect_uri", "dest", "destination", "r"):
            values = query.get(key)
            if not values:
                continue
            candidate = unquote(str(values[0] or "").strip())
            if candidate.lower().startswith(("http://", "https://")):
                next_url = candidate
                break

        if not next_url:
            break
        current = next_url

    return current


def _canonical_image_key(url: str) -> str:
    parsed = urlparse(str(url or "").strip().lower())
    host = parsed.netloc.removeprefix("www.")
    path = re.sub(r"/+", "/", parsed.path or "/")

    raw_query = parse_qs(parsed.query, keep_blank_values=False)
    stable_pairs: list[tuple[str, str]] = []
    for key, values in raw_query.items():
        normalized_key = str(key or "").strip().lower()
        if not normalized_key or normalized_key in TRACKING_QUERY_KEYS:
            continue
        if normalized_key not in IMAGE_ID_QUERY_KEYS:
            continue
        normalized_value = str(values[0] or "").strip().lower() if values else ""
        if not normalized_value:
            continue
        stable_pairs.append((normalized_key, normalized_value))

    stable_pairs.sort(key=lambda item: item[0])
    stable_query = urlencode(stable_pairs)
    return f"{host}{path}?{stable_query}" if stable_query else f"{host}{path}"


def canonical_image_key(url: str | None) -> str:
    value = str(url or "").strip()
    if not value:
        return ""
    return _canonical_image_key(value)


def _visual_image_key(url: str) -> str:
    parsed = urlparse(str(url or "").strip().lower())
    host = parsed.netloc.removeprefix("www.")
    path = unquote(parsed.path or "/")
    path = re.sub(r"/+", "/", path)
    path = re.sub(r"(?<!\d)\d{2,4}[xX]\d{2,4}(?!\d)", "{size}", path)
    path = re.sub(r"(w|h|width|height|q|quality)[=_-]?\d{1,4}", r"\1={n}", path)
    path = path.rstrip("/") or "/"
    return f"{host}{path}"


def _rank_image_urls(
    urls: list[str],
    topic: str,
    source_url: str | None,
    context_by_url: dict[str, str] | None = None,
) -> list[str]:
    source_domain = _source_domain(source_url)
    tokens = _topic_tokens(topic)
    context_by_url = context_by_url or {}

    scored: list[tuple[float, str]] = []
    for index, raw in enumerate(urls):
        url = str(raw or "").strip()
        if not url:
            continue

        parsed = urlparse(url)
        haystack = f"{parsed.netloc} {parsed.path} {parsed.query}".lower()
        context_haystack = str(context_by_url.get(url) or "").lower()
        score = 0.0

        if source_domain and source_domain in parsed.netloc.lower():
            score += 60.0
        if _looks_like_news_photo(url):
            score += 25.0

        width_hint, height_hint = _extract_dimension_hints(url)
        if width_hint is not None:
            if width_hint >= 1280:
                score += 14.0
            elif width_hint >= 1024:
                score += 10.0
            elif width_hint >= MIN_PUBLIC_IMAGE_WIDTH:
                score += 6.0
            elif width_hint >= 720:
                score += 2.0
        if height_hint is not None:
            if height_hint >= 720:
                score += 6.0
            elif height_hint >= 480:
                score += 3.0
            elif height_hint >= MIN_PUBLIC_IMAGE_HEIGHT:
                score += 1.5
        else:
            score -= 4.0

        token_hits_url = 0
        token_hits_context = 0
        for token in tokens[:8]:
            if token in haystack:
                token_hits_url += 1
            if token in context_haystack:
                token_hits_context += 1

        score += min(token_hits_url * 4.0, 20.0)
        score += min(token_hits_context * 6.0, 30.0)

        if _is_generic_stock_candidate(url, context_haystack):
            if token_hits_url == 0 and token_hits_context == 0:
                score -= 30.0
            else:
                score -= 10.0

        if not source_domain and token_hits_url == 0 and token_hits_context == 0:
            score -= 8.0

        score -= index * 0.05
        scored.append((score, url))

    scored.sort(key=lambda item: item[0], reverse=True)
    return [url for _, url in scored]


def _extract_image_urls_from_html_blob(html: str, base_url: str | None) -> list[str]:
    if not html:
        return []

    matches = re.findall(
        r"https?://[^\s\"'<>]+?\.(?:jpg|jpeg|png|webp|avif)(?:\?[^\s\"'<>]*)?",
        html,
        flags=re.IGNORECASE,
    )

    candidates: list[str] = []
    for raw in matches:
        normalized = _normalize_candidate_url(raw, base_url)
        if normalized and _looks_like_news_photo(normalized):
            candidates.append(normalized)
    return candidates


def _filter_topical_candidates(
    urls: list[str],
    topic: str,
    source_url: str | None,
    context_by_url: dict[str, str],
) -> list[str]:
    tokens = _topic_tokens(topic)
    if not tokens:
        return urls

    source_domain = _source_domain(source_url)
    filtered: list[str] = []
    for url in urls:
        parsed = urlparse(url)
        haystack = f"{parsed.netloc} {parsed.path} {parsed.query}".lower()
        context = str(context_by_url.get(url) or "").lower()

        token_hits = 0
        for token in tokens:
            if token in haystack or token in context:
                token_hits += 1

        if token_hits > 0:
            filtered.append(url)
            continue

        if source_domain and source_domain in parsed.netloc.lower() and _looks_like_news_photo(url):
            filtered.append(url)

    return filtered


def _collect_unique_urls(values: list[str], limit: int) -> list[str]:
    result: list[str] = []
    seen_keys: set[str] = set()
    seen_visual_keys: set[str] = set()
    domain_counts: dict[str, int] = {}
    # Keep diversity so feed doesn't show 3-4 near-identical CDN variants.
    max_per_domain = 2 if limit >= 4 else 3

    for value in values:
        candidate = str(value or "").strip()
        if not candidate:
            continue

        dedupe_key = _canonical_image_key(candidate)
        visual_key = _visual_image_key(candidate)
        if not dedupe_key or dedupe_key in seen_keys:
            continue
        if visual_key in seen_visual_keys:
            continue

        domain = _source_domain(candidate)
        if domain:
            count = domain_counts.get(domain, 0)
            if count >= max_per_domain:
                continue
            domain_counts[domain] = count + 1

        seen_keys.add(dedupe_key)
        seen_visual_keys.add(visual_key)
        result.append(candidate)
        if len(result) >= limit:
            break

    if len(result) >= limit:
        return result

    # Second pass: relax domain diversity if we don't have enough images.
    for value in values:
        candidate = str(value or "").strip()
        if not candidate:
            continue
        dedupe_key = _canonical_image_key(candidate)
        visual_key = _visual_image_key(candidate)
        if not dedupe_key or dedupe_key in seen_keys:
            continue
        if visual_key in seen_visual_keys:
            continue
        seen_keys.add(dedupe_key)
        seen_visual_keys.add(visual_key)
        result.append(candidate)
        if len(result) >= limit:
            break

    return result


def _fallback_image_urls(topic: str, start_sig: int, count: int) -> list[str]:
    bucket = _choose_fallback_bucket(topic)
    pool = CURATED_TOPIC_FALLBACK_IMAGES.get(bucket) or CURATED_TOPIC_FALLBACK_IMAGES["general"]
    if not pool:
        fallback_topic = re.sub(r"\s+", "-", topic.strip().lower()) or "news"
        return [
            f"https://picsum.photos/seed/{fallback_topic}-{idx}/1280/720"
            for idx in range(start_sig, start_sig + count)
        ]

    result: list[str] = []
    for offset in range(count):
        result.append(pool[(start_sig + offset) % len(pool)])
    return result


async def fetch_media_urls(
    topic: str,
    limit: int = 4,
    source_url: str | None = None,
    source_image_url: str | None = None,
) -> list[str]:
    topic = _build_media_topic(topic)
    limit = min(4, max(1, int(limit)))
    source_url = _unwrap_redirect_url(source_url)
    search_tokens = _topic_tokens(topic)
    search_query = " ".join(search_tokens[:8]) or topic
    title_query = " ".join(search_tokens[:5]) or search_query
    context_by_url: dict[str, str] = {}

    async def _fetch_newsapi() -> dict[str, Any]:
        if not settings.NEWS_API_KEY:
            return {"articles": []}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                NEWS_API_URL,
                params={
                    "q": search_query,
                    "qInTitle": title_query,
                    "searchIn": "title,description",
                    "pageSize": max(16, limit * 4),
                    "sortBy": "relevancy",
                    "apiKey": settings.NEWS_API_KEY,
                },
            )
        response.raise_for_status()
        return response.json()

    async def _fetch_google_images() -> dict[str, Any]:
        if not settings.GOOGLE_CSE_API_KEY or not settings.GOOGLE_CSE_ID:
            return {"items": []}

        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                GOOGLE_CSE_IMAGE_SEARCH_URL,
                params={
                    "key": settings.GOOGLE_CSE_API_KEY,
                    "cx": settings.GOOGLE_CSE_ID,
                    "q": f"{search_query} news photo",
                    "searchType": "image",
                    "num": min(10, max(4, limit * 2)),
                    "imgType": "photo",
                    "safe": "active",
                    "hl": "uz",
                    "gl": "uz",
                },
            )
        response.raise_for_status()
        return response.json()

    async def _fetch_wikimedia_images() -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.get(
                WIKIMEDIA_API_URL,
                params={
                    "action": "query",
                    "generator": "search",
                    "gsrnamespace": 6,
                    "gsrlimit": max(8, limit * 3),
                    "gsrsearch": search_query,
                    "prop": "imageinfo",
                    "iiprop": "url",
                    "iiurlwidth": 1280,
                    "format": "json",
                    "formatversion": 2,
                    "origin": "*",
                },
            )
        response.raise_for_status()
        return response.json()

    async def _fetch_source_images(source_url: str) -> dict[str, Any]:
        if not source_url:
            return {"urls": []}

        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(
                source_url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                },
            )
        response.raise_for_status()

        content_type = str(response.headers.get("content-type") or "").lower()
        if "html" not in content_type:
            return {"urls": []}

        parser = _ImageCandidateParser(source_url)
        parser.feed(response.text or "")
        for image_url, image_context in parser.context_by_url.items():
            context_by_url[image_url] = f"{context_by_url.get(image_url, '')} {image_context}".strip()
        regex_candidates = _extract_image_urls_from_html_blob(response.text or "", source_url)
        ranked = _rank_image_urls(
            parser.candidates + regex_candidates,
            topic=topic,
            source_url=source_url,
            context_by_url=context_by_url,
        )
        filtered = [url for url in ranked if _looks_like_news_photo(url)]
        return {"urls": filtered[:16]}

    candidates: list[str] = []

    min_required = 1

    normalized_source_image = _normalize_candidate_url(source_image_url)
    if normalized_source_image:
        normalized_source_image = _upgrade_known_image_url_quality(normalized_source_image)
    if normalized_source_image and _looks_like_news_photo(normalized_source_image):
        candidates.append(normalized_source_image)
        context_by_url[normalized_source_image] = topic

    if source_url:
        source_cache_key = build_cache_key("media:source-images:v3", {"source_url": source_url, "topic": topic})
        try:
            source_payload = await get_or_set_json(
                source_cache_key,
                ttl_seconds=3600,
                fetcher=lambda: _fetch_source_images(source_url or ""),
            )
            candidates.extend([str(url) for url in (source_payload.get("urls") or [])])
        except httpx.HTTPError:
            pass

    cache_key = build_cache_key("newsapi:media:v2", {"topic": topic, "limit": limit})
    try:
        payload = await get_or_set_json(cache_key, ttl_seconds=1800, fetcher=_fetch_newsapi)
    except httpx.HTTPError:
        payload = {"articles": []}

    for article in payload.get("articles") or []:
        image_url = _normalize_candidate_url(article.get("urlToImage"))
        if image_url:
            image_url = _upgrade_known_image_url_quality(image_url)
        if image_url and _looks_like_news_photo(image_url):
            candidates.append(image_url)
            article_context = " ".join(
                [
                    str(article.get("title") or ""),
                    str(article.get("description") or ""),
                    str(article.get("content") or ""),
                    str((article.get("source") or {}).get("name") or ""),
                ]
            ).strip()
            context_by_url[image_url] = f"{context_by_url.get(image_url, '')} {article_context}".strip()

    google_cache_key = build_cache_key("google-cse:media:v2", {"topic": topic, "limit": limit})
    try:
        google_payload = await get_or_set_json(google_cache_key, ttl_seconds=1800, fetcher=_fetch_google_images)
    except httpx.HTTPError:
        google_payload = {"items": []}

    for item in google_payload.get("items") or []:
        image_url = _normalize_candidate_url(item.get("link"))
        if image_url:
            image_url = _upgrade_known_image_url_quality(image_url)
        if image_url and _looks_like_news_photo(image_url):
            candidates.append(image_url)
            google_context = " ".join(
                [
                    str(item.get("title") or ""),
                    str(item.get("snippet") or ""),
                    str(item.get("displayLink") or ""),
                ]
            ).strip()
            context_by_url[image_url] = f"{context_by_url.get(image_url, '')} {google_context}".strip()

    wikimedia_cache_key = build_cache_key("wikimedia:media:v1", {"topic": topic, "limit": limit})
    try:
        wikimedia_payload = await get_or_set_json(wikimedia_cache_key, ttl_seconds=3600, fetcher=_fetch_wikimedia_images)
    except httpx.HTTPError:
        wikimedia_payload = {"query": {"pages": []}}

    pages = ((wikimedia_payload.get("query") or {}).get("pages") or [])
    if isinstance(pages, list):
        for page in pages:
            image_info = ((page or {}).get("imageinfo") or [])
            if not isinstance(image_info, list) or not image_info:
                continue
            image_url = _normalize_candidate_url((image_info[0] or {}).get("thumburl") or (image_info[0] or {}).get("url"))
            if image_url:
                image_url = _upgrade_known_image_url_quality(image_url)
            if image_url and _looks_like_news_photo(image_url):
                candidates.append(image_url)
                wiki_context = str((page or {}).get("title") or "").strip()
                context_by_url[image_url] = f"{context_by_url.get(image_url, '')} {wiki_context}".strip()

    ranked_candidates = _rank_image_urls(
        candidates,
        topic=topic,
        source_url=source_url,
        context_by_url=context_by_url,
    )
    topical_candidates = _filter_topical_candidates(ranked_candidates, topic, source_url, context_by_url)
    primary_candidates = topical_candidates if len(topical_candidates) >= min_required else ranked_candidates
    urls = _collect_unique_urls(primary_candidates, limit)

    if len(urls) < min_required:
        urls.extend(_fallback_image_urls(topic, start_sig=len(urls), count=max(0, limit - len(urls))))
        urls = _collect_unique_urls(urls, limit)

    if urls:
        return urls[:limit]

    return _fallback_image_urls(topic, start_sig=0, count=limit)


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
    query_parts = [_build_media_topic(topic)]
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

        videos.append(f"https://www.youtube.com/watch?v={video_id}")

    videos = _collect_unique_urls(videos, limit)

    if videos:
        return videos

    return _video_template_urls()[:limit]
