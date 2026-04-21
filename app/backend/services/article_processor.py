from __future__ import annotations
import asyncio
import logging
from typing import Optional, Callable, Awaitable, List
from bs4 import BeautifulSoup

from app.backend.services.content_extractors import extract_by_domain
from app.backend.services.today_pipeline_utils import extract_date
from app.backend.services.site_parsers import parse_article_by_domain
from app.backend.services.article_detector import ArticleDetector
from app.backend.services.content_filters import is_advertisement

LOG = logging.getLogger("article_processor")
LOG.addHandler(logging.NullHandler())

_DET = ArticleDetector()


async def process_article(session, url: str, fetch: Callable[[Optional[object], str], Awaitable[Optional[str]]]) -> tuple[Optional[dict], Optional[str]]:
    """Single unified article processing: fetch -> validate -> extract -> date.

    - `fetch(session, url)` must be an async callable that returns HTML string or None.
    - Returns tuple `(item_dict, None)` on success or `(None, reason)` when skipped.
    """
    try:
        html = await fetch(session, url)
    except Exception as e:
        LOG.debug("fetch failed for %s: %s", url, e)
        print(f"[ARTICLE] SKIP (fetch error): {url}")
        return None, "fetch_error"

    if not html:
        print(f"[ARTICLE] SKIP (no html): {url}")
        return None, "no_html"

    # deep HTML check via detector (score-based)
    try:
        if not _DET.is_article_page(html):
            print(f"[ARTICLE] SKIP (not article): {url}")
            return None, "not_article"
    except Exception:
        LOG.exception("detector failed for %s", url)
        print(f"[ARTICLE] SKIP (detector error): {url}")
        return None, "detector_error"

    # parse and extract site-specific content and title
    soup = BeautifulSoup(html, "lxml")
    title = ""
    try:
        parsed = parse_article_by_domain(html, url)
        title = parsed.get("title") or ""
    except Exception:
        title = (soup.title.string.strip() if soup.title and soup.title.string else "")

    try:
        content = extract_by_domain(url, soup)
    except Exception:
        LOG.exception("extract_by_domain failed for %s", url)
        content = None

    if not content or len(content) < 300:
        print(f"[ARTICLE] SKIP (short): {url}")
        return None, "short"

    # filter promotional/advertorial content
    try:
        if is_advertisement(content, title):
            print(f"[FILTER] AD skipped: {url}")
            return None, "ad"
    except Exception:
        LOG.exception("ad filter failed for %s", url)

    # extract date (best-effort)
    try:
        published = extract_date(html, url)
    except Exception:
        LOG.exception("date extraction failed for %s", url)
        published = None

    print(f"[ARTICLE] OK: {url}")
    return {"url": url, "title": title, "content": content, "published_at": published}, None


async def process_all(session, urls: List[str], fetch: Callable[[Optional[object], str], Awaitable[Optional[str]]], concurrency: int = 10) -> tuple[List[dict], dict]:
    sem = asyncio.Semaphore(concurrency)

    stats = {
        "processed": 0,
        "ads_skipped": 0,
        "invalid": 0,
        "short": 0,
        "fetch_error": 0,
        "no_html": 0,
        "not_article": 0,
        "detector_error": 0,
    }

    async def worker(u: str):
        async with sem:
            try:
                item, reason = await process_article(session, u, fetch)
                if item:
                    stats["processed"] += 1
                    return item
                else:
                    # categorize skipped reason
                    if reason == "ad":
                        stats["ads_skipped"] += 1
                    elif reason in ("short",):
                        stats["short"] += 1
                        stats["invalid"] += 1
                    elif reason == "fetch_error":
                        stats["fetch_error"] += 1
                        stats["invalid"] += 1
                    elif reason == "no_html":
                        stats["no_html"] += 1
                        stats["invalid"] += 1
                    elif reason == "not_article":
                        stats["not_article"] += 1
                        stats["invalid"] += 1
                    elif reason == "detector_error":
                        stats["detector_error"] += 1
                        stats["invalid"] += 1
                    else:
                        stats["invalid"] += 1
                    return None
            except Exception:
                LOG.exception("worker failed for %s", u)
                stats["invalid"] += 1
                return None

    tasks = [asyncio.create_task(worker(u)) for u in urls]
    results = await asyncio.gather(*tasks)
    return [r for r in results if r], stats


__all__ = ["process_article", "process_all"]
