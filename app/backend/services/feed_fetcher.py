from __future__ import annotations

import asyncio
import re
from typing import List
from urllib.parse import urljoin, urlparse

import feedparser
from bs4 import BeautifulSoup

from app.backend.core.logging import ContextLogger
from app.backend.services.http_client import get_async_client
from app.backend.services.media_service import fetch_media_urls
from app.backend.services.site_parsers import parse_article_by_domain
from app.backend.services.ingestion_service import create_raw_news


logger = ContextLogger(__name__)

# Production-tuned defaults
# Number of entries to fetch per RSS feed and number of links per site frontpage
DEFAULT_PER_RSS_LIMIT = 30
DEFAULT_PER_SITE_LIMIT = 100
# Concurrency (semaphores) for article processing - tune according to worker resources
RSS_CONCURRENCY = 16
SITE_CONCURRENCY = 12


_LINK_FILTER_RE = re.compile(r"^https?://", flags=re.IGNORECASE)


def _same_domain(url: str, base: str) -> bool:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.") == urlparse(base).netloc.lower().removeprefix("www.")
    except Exception:
        return False


def _is_media_file(url: str) -> bool:
    url = (url or "").lower()
    return any(url.endswith(ext) for ext in (".jpg", ".jpeg", ".png", ".webp", ".avif"))


def _clean_text(s: str) -> str:
    return (s or "").strip()


def _largest_text_block(soup: BeautifulSoup) -> str:
    # Find candidate containers and choose the one with the most paragraph text
    candidates = []
    # Prefer semantic <article>
    for tag in soup.find_all(["article", "main"]):
        text = "\n\n".join(p.get_text(strip=True) for p in tag.find_all("p"))
        if text:
            candidates.append(text)

    # Look for class-name hints
    hints = ("article", "post", "content", "news", "detail", "entry")
    for hint in hints:
        for tag in soup.find_all(True, class_=lambda v: v and hint in v.lower()):
            text = "\n\n".join(p.get_text(strip=True) for p in tag.find_all("p"))
            if text:
                candidates.append(text)

    # Fallback: largest contiguous set of <p> in body
    body = soup.body or soup
    paragraphs = body.find_all("p")
    if paragraphs:
        # group consecutive paragraphs
        groups = []
        current = []
        last_parent = None
        for p in paragraphs:
            parent = p.parent
            if last_parent is None or parent is last_parent:
                current.append(p)
            else:
                groups.append(current)
                current = [p]
            last_parent = parent
        if current:
            groups.append(current)

        for g in groups:
            text = "\n\n".join(p.get_text(strip=True) for p in g)
            if text:
                candidates.append(text)

    if not candidates:
        return ""

    # Choose longest candidate
    chosen = max(candidates, key=lambda t: len(t))
    return _clean_text(chosen)


def _extract_title(soup: BeautifulSoup) -> str:
    # Try common meta tags then h1/title
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return _clean_text(og.get("content"))
    twitter = soup.find("meta", attrs={"name": "twitter:title"})
    if twitter and twitter.get("content"):
        return _clean_text(twitter.get("content"))
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return _clean_text(h1.get_text(strip=True))
    if soup.title and soup.title.string:
        return _clean_text(soup.title.string)
    return ""


def _extract_og_image(soup: BeautifulSoup) -> str | None:
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        return _clean_text(og.get("content"))
    tw = soup.find("meta", attrs={"name": "twitter:image"})
    if tw and tw.get("content"):
        return _clean_text(tw.get("content"))
    return None


async def _fetch_text(url: str) -> str | None:
    try:
        client = await get_async_client()
        resp = await client.get(url)
        resp.raise_for_status()
        content_type = str(resp.headers.get("content-type") or "").lower()
        if "html" in content_type or "xml" in content_type or True:
            return resp.text
        return None
    except Exception as exc:  # pragma: no cover - network issues
        logger.warning("Failed to fetch url", url=url, error=str(exc))
        return None


async def _process_article(session, article_url: str, html: str | None) -> dict | None:
    if not article_url or not html:
        return None

    soup = BeautifulSoup(html or "", "html.parser")

    # Use site-specific parsing when available to extract title/body reliably
    parsed = parse_article_by_domain(html, article_url)
    title = parsed.get("title") or _extract_title(soup) or article_url
    raw_text = parsed.get("raw_text") or _largest_text_block(soup) or _clean_text(soup.get_text())

    # Try to find meta og:image first, allow site-parsed og image
    og_image = parsed.get("og_image") or _extract_og_image(soup)
    media_candidates = await fetch_media_urls(title or "news", limit=1, source_url=article_url, source_image_url=og_image)
    image_url = media_candidates[0] if media_candidates else og_image

    payload = {
        "title": title,
        "source_url": article_url,
        "image_url": image_url,
        "raw_text": raw_text,
        "category": None,
        "region": None,
        "is_urgent": False,
    }

    try:
        result = await create_raw_news(session, payload)
        logger.info("Ingested article", title=title, url=article_url, id=result.get("id"))
        return result
    except Exception as exc:  # pragma: no cover - DB or constraint issues
        logger.exception("Failed creating raw_news", error=str(exc), url=article_url, title=title)
        return None


async def ingest_rss_feed(session, rss_url: str, limit: int = 10) -> int:
    """Fetch RSS feed and ingest entries asynchronously."""
    try:
        client = await get_async_client()
        resp = await client.get(rss_url)
        resp.raise_for_status()
        feed = feedparser.parse(resp.content)
    except Exception as exc:  # pragma: no cover - network issues
        logger.warning("Failed to fetch or parse RSS", url=rss_url, error=str(exc))
        return 0

    entries = getattr(feed, "entries", []) or []
    count = 0
    sem = asyncio.Semaphore(8)

    async def _handle(entry):
        nonlocal count
        async with sem:
            link = entry.get("link") or entry.get("id")
            if not link or not _LINK_FILTER_RE.match(link):
                return
            title = _clean_text(entry.get("title") or "")
            content = ""
            if entry.get("content"):
                try:
                    content = entry.get("content")[0].get("value", "")
                except Exception:
                    content = entry.get("summary", "")
            else:
                content = entry.get("summary", "")

            # try feed-provided images
            image_url = None
            if entry.get("media_content"):
                try:
                    media = entry.get("media_content")
                    if isinstance(media, (list, tuple)) and media:
                        image_url = media[0].get("url")
                except Exception:
                    image_url = None

            if not image_url:
                candidates = await fetch_media_urls(title or link, limit=1, source_url=link)
                image_url = candidates[0] if candidates else None

            payload = {
                "title": title or link,
                "source_url": link,
                "image_url": image_url,
                "raw_text": content,
                "category": None,
                "region": None,
                "is_urgent": False,
            }

            try:
                await create_raw_news(session, payload)
                count += 1
                logger.info("Ingested RSS entry", feed=rss_url, url=link, title=title)
            except Exception as exc:
                logger.exception("Failed to create raw_news from RSS entry", error=str(exc), url=link)

    tasks = [asyncio.create_task(_handle(e)) for e in entries[:limit]]
    if tasks:
        await asyncio.gather(*tasks)

    return count


async def ingest_site_frontpage(session, base_url: str, limit_links: int = 20) -> int:
    """Scrape a site's front page for article links and ingest them."""
    html = await _fetch_text(base_url)
    if not html:
        return 0
    soup = BeautifulSoup(html, "html.parser")
    anchors = soup.find_all("a", href=True)
    seen = set()
    links: List[str] = []
    for a in anchors:
        href = a.get("href")
        if not href:
            continue
    
        url = urljoin(base_url, href)
        if url in seen:
            continue
        seen.add(url)
        # filter same-domain and likely article
        if not _same_domain(url, base_url):
            continue
        parsed = urlparse(url)
        # skip anchors, mailto, JS
        if parsed.scheme not in ("http", "https"):
            continue
        # skip obvious non-article file types
        if any(parsed.path.lower().endswith(ext) for ext in (".jpg", ".png", ".pdf", ".zip", ".json", ".css", ".js")):
            continue
        # heuristic: prefer paths longer than 3 chars or containing keywords
        if len(parsed.path or "") < 2 and not parsed.query:
            continue
        links.append(url)
        if len(links) >= limit_links:
            break

    count = 0
    sem = asyncio.Semaphore(SITE_CONCURRENCY)

    async def _handle_link(link: str):
        nonlocal count
        async with sem:
            html = await _fetch_text(link)
            if not html:
                return
            result = await _process_article(session, link, html)
            if result:
                count += 1

    tasks = [asyncio.create_task(_handle_link(l)) for l in links]
    if tasks:
        await asyncio.gather(*tasks)

    return count


async def ingest_many(
    session,
    rss_sources: list[str] | None = None,
    site_sources: list[str] | None = None,
    per_rss_limit: int = DEFAULT_PER_RSS_LIMIT,
    per_site_limit: int = DEFAULT_PER_SITE_LIMIT,
):
    rss_sources = rss_sources or [
        "https://gazeta.uz/ru/rss",
        "https://daryo.uz/rss",
    ]
    site_sources = site_sources or [
        "https://uz24.uz",
        "https://uznews.uz",
        "https://kun.uz",
        "https://podrobno.uz",
    ]

    tasks = []
    for rss in rss_sources:
        tasks.append(asyncio.create_task(ingest_rss_feed(session, rss, limit=per_rss_limit)))
    for site in site_sources:
        tasks.append(asyncio.create_task(ingest_site_frontpage(session, site, limit_links=per_site_limit)))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    summary = {"completed": [], "errors": []}
    for src, res in zip(rss_sources + site_sources, results):
        if isinstance(res, Exception):
            logger.exception("Source ingest failed", source=src, error=str(res))
            summary["errors"].append({"source": src, "error": str(res)})
        else:
            summary["completed"].append({"source": src, "count": int(res)})

    return summary
