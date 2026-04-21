"""Utilities for robust "today-only" scraping: link collection, date extraction, normalization.

Designed for httpx + BeautifulSoup + asyncio. Keep functions small and testable.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
import hashlib
from app.backend.services.article_detector import ArticleDetector
from app.backend.services.ai_enrichment import extract_text_from_html, summarize_text, classify_text
import os

try:
    from dateutil import parser as dateutil_parser
except Exception:
    dateutil_parser = None

LOG = logging.getLogger("today_pipeline")
LOG.addHandler(logging.NullHandler())

USER_AGENT = "pdads_today_scraper/1.0 (+https://example)"
TZ = ZoneInfo("Asia/Tashkent")
CONCURRENCY = 8
REQUEST_TIMEOUT = 15.0
MAX_LINKS_PER_SITE = 500
FALLBACK_SAMPLE_RATE = 0.2  # deterministic sampling for URLs that fail cheap URL check
AI_ENABLED = os.getenv("ENABLE_AI", "1").lower() in ("1", "true", "yes")

# conservative non-article patterns to skip on listing page
_non_article_href_patterns = re.compile(
    r"(mailto:|tel:|#|/tag/|/category/|/authors?/|/search|/subscribe|/rss|/wp-content/|javascript:)",
    flags=re.I,
)


async def _fetch_html(client: httpx.AsyncClient, url: str, attempts: int = 3) -> Optional[str]:
    backoff = 0.5
    for i in range(attempts):
        try:
            resp = await client.get(url, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            LOG.debug("fetch %s failed attempt %d: %s", url, i + 1, e)
            await asyncio.sleep(backoff)
            backoff *= 2
    LOG.warning("fetch failed after %d attempts: %s", attempts, url)
    return None


def _same_domain(candidate: str, base: str) -> bool:
    from urllib.parse import urlparse

    a = urlparse(candidate)
    b = urlparse(base)
    if not a.netloc:
        return True
    return a.netloc.lower().lstrip("www.") == b.netloc.lower().lstrip("www.")


async def extract_links(client: httpx.AsyncClient, listing_url: str, max_links: int = MAX_LINKS_PER_SITE) -> List[str]:
    """Collect same-domain candidate links from listing page with minimal filtering.

    Only skip obvious non-article hrefs; do NOT rely on link path regex here.
    """
    html = await _fetch_html(client, listing_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "lxml")
    anchors = soup.find_all("a", href=True)
    LOG.debug("[%s] anchors found: %d", listing_url, len(anchors))
    seen = set()
    results: List[str] = []
    from urllib.parse import urljoin

    for a in anchors:
        href = (a.get("href") or "").strip()
        if not href:
            continue
        if _non_article_href_patterns.search(href):
            LOG.debug("skipping obvious non-article href: %s (from %s)", href, listing_url)
            continue
        full = urljoin(listing_url, href)
        if not _same_domain(full, listing_url):
            continue
        full = full.split("#", 1)[0]
        if full in seen:
            continue
        seen.add(full)
        results.append(full)
        if len(results) >= max_links:
            break

    LOG.info("[%s] collected %d candidate links", listing_url, len(results))
    return results


def _search_json_ld_for_date(soup: BeautifulSoup) -> Optional[str]:
    scripts = soup.find_all("script", type="application/ld+json")
    if not scripts:
        return None
    for s in scripts:
        text = s.string or s.get_text("")
        if not text:
            continue
        try:
            data = json.loads(text)
        except Exception:
            try:
                data = json.loads(f"[{text}]")
            except Exception:
                continue

        def _walk(obj: Any) -> Optional[str]:
            if isinstance(obj, dict):
                for k in ("datePublished", "dateCreated", "uploadDate"):
                    if k in obj and obj[k]:
                        return str(obj[k])
                if "@graph" in obj:
                    for item in obj["@graph"]:
                        d = _walk(item)
                        if d:
                            return d
                if obj.get("@type", "").lower() in ("newsarticle", "article"):
                    for k in ("datePublished", "dateCreated", "uploadDate"):
                        if k in obj and obj[k]:
                            return str(obj[k])
                for v in obj.values():
                    d = _walk(v)
                    if d:
                        return d
            elif isinstance(obj, list):
                for item in obj:
                    d = _walk(item)
                    if d:
                        return d
            return None

        found = _walk(data)
        if found:
            return found
    return None


def _search_meta_for_date(soup: BeautifulSoup) -> Optional[str]:
    meta = soup.select_one('meta[property="article:published_time"], meta[name="date"], meta[itemprop="datePublished"], meta[name="pubdate"]')
    if meta and meta.get("content"):
        return meta.get("content").strip()
    return None


def _search_time_tag_for_date(soup: BeautifulSoup) -> Optional[str]:
    t = soup.find("time")
    if not t:
        return None
    if t.get("datetime"):
        return t.get("datetime").strip()
    text = t.get_text(" ", strip=True)
    return text if text else None


_russian_tokens = ("сегодня", "вчера", "час", "часа", "часов", "минут", "минуту", "минуты")
_uzbek_tokens = ("bugun", "kecha", "soat", "daqiqa", "soniya", "oldin")


def _parse_relative_or_local_text(text: str) -> Optional[datetime]:
    if not text:
        return None
    t = text.lower().strip()
    now = datetime.now(TZ)
    # hh:mm
    m = re.search(r"(\d{1,2}):(\d{2})", t)
    if m:
        h = int(m.group(1)); mi = int(m.group(2))
        return datetime(now.year, now.month, now.day, h, mi, tzinfo=TZ)
    if any(tok in t for tok in ("today", "сегодня", "bugun")):
        return datetime(now.year, now.month, now.day, tzinfo=TZ)
    if any(tok in t for tok in ("yesterday", "вчера", "kecha")):
        d = now.date() - timedelta(days=1)
        return datetime(d.year, d.month, d.day, tzinfo=TZ)
    rh = re.search(r"(\d+)\s*(hours|hour|час|часа|soat|soat oldin|oldin)", t)
    if rh:
        val = int(rh.group(1))
        return now - timedelta(hours=val)
    rm = re.search(r"(\d+)\s*(minutes|min|минут|daqiqa)", t)
    if rm:
        val = int(rm.group(1))
        return now - timedelta(minutes=val)
    if dateutil_parser:
        try:
            dt = dateutil_parser.parse(t, dayfirst=True, fuzzy=True)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=TZ)
            return dt
        except Exception:
            return None
    return None


def extract_date(html: str, url: str) -> Optional[datetime]:
    """Try multiple strategies to extract publication date from article HTML.

    Returns timezone-aware datetime in TZ, or None.
    """
    soup = BeautifulSoup(html, "lxml")
    # 1 JSON-LD
    jd = _search_json_ld_for_date(soup)
    if jd:
        dt = _parse_candidate_date_string(jd, source="json-ld", url=url)
        if dt:
            return dt
    # 2 meta
    md = _search_meta_for_date(soup)
    if md:
        dt = _parse_candidate_date_string(md, source="meta", url=url)
        if dt:
            return dt
    # 3 time tag
    td = _search_time_tag_for_date(soup)
    if td:
        dt = _parse_candidate_date_string(td, source="time-tag", url=url)
        if dt:
            return dt
    # 4 selectors
    selectors = [".post-meta", ".article-meta", ".datetime", ".date", "meta[name='pubdate']"]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = el.get_text(" ", strip=True)
            dt = _parse_candidate_date_string(txt, source=f"selector:{sel}", url=url)
            if dt:
                return dt
    # 5 page text heuristic
    body_txt = soup.get_text(" ", strip=True)[:1000]
    dt = _parse_candidate_date_string(body_txt, source="page-text", url=url)
    if dt:
        return dt
    LOG.debug("no date found for %s", url)
    return None


def _parse_candidate_date_string(txt: str, source: str, url: str) -> Optional[datetime]:
    txt = (txt or "").strip()
    if not txt:
        return None
    dt = _parse_relative_or_local_text(txt)
    if dt:
        LOG.debug("parsed date (fast) from %s for %s -> %s", source, url, dt.isoformat())
        return _ensure_tz(dt)
    if dateutil_parser:
        try:
            dt2 = dateutil_parser.parse(txt, dayfirst=True, fuzzy=True)
            if dt2.tzinfo is None:
                dt2 = dt2.replace(tzinfo=TZ)
            LOG.debug("parsed date (dateutil) from %s for %s -> %s", source, url, dt2.isoformat())
            return dt2
        except Exception as e:
            LOG.debug("dateutil failed on %s (%s): %s", url, source, e)
    m = re.search(r"(\d{1,2})[./](\d{1,2})[./](\d{2,4})", txt)
    if m:
        d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if y < 100:
            y += 2000
        try:
            dt3 = datetime(y, mo, d, tzinfo=TZ)
            LOG.debug("parsed date (dmy) from %s for %s -> %s", source, url, dt3.isoformat())
            return dt3
        except Exception:
            pass
    LOG.debug("failed to parse date string from %s for %s: %r", source, url, txt[:120])
    return None


def _ensure_tz(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=TZ)
    return dt.astimezone(TZ)


def is_today(dt: Optional[datetime]) -> bool:
    if not dt:
        return False
    now = datetime.now(TZ)
    return dt.astimezone(TZ).date() == now.date()


def looks_js_rendered(html: str) -> bool:
    soup = BeautifulSoup(html, "lxml")
    scripts = len(soup.find_all("script"))
    anchors = len(soup.find_all("a"))
    text_len = len(soup.get_text(" ", strip=True))
    return (scripts > anchors * 3) or (anchors < 5 and text_len < 200)


async def find_today_articles(frontpages: List[str]) -> List[Dict[str, Any]]:
    headers = {"User-Agent": USER_AGENT}
    results: List[Dict[str, Any]] = []
    det = ArticleDetector()
    stats = {"candidates": 0, "accepted": 0, "accepted_by_url": 0, "accepted_by_fallback": 0, "skipped": 0}
    async with httpx.AsyncClient(follow_redirects=True, headers=headers) as client:
        sem = asyncio.Semaphore(CONCURRENCY)

        async def process_site(front: str):
            links = await extract_links(client, front, max_links=MAX_LINKS_PER_SITE)
            LOG.info("site %s: %d candidate links", front, len(links))
            tasks = []
            for url in links:
                async def _proc(u=url):
                    async with sem:
                        html = await _fetch_html(client, u)
                        stats["candidates"] += 1
                        if not html:
                            LOG.info("skip %s — fetch failed", u)
                            stats["skipped"] += 1
                            return
                        if looks_js_rendered(html):
                            LOG.info("page looks JS-rendered, mark for JS fallback: %s", u)
                        dt = extract_date(html, u)
                        if not dt:
                            LOG.info("skip %s — no date extracted", u)
                            stats["skipped"] += 1
                            return
                        if not is_today(dt):
                            LOG.debug("skip %s — date not today: %s", u, dt.isoformat())
                            stats["skipped"] += 1
                            return

                        # Article detection: cheap URL check + deterministic fallback sampling
                        is_url_candidate = det.is_article_url(u)
                        run_deep = False
                        if is_url_candidate:
                            run_deep = True
                        else:
                            h = hashlib.sha256(u.encode("utf-8")).digest()
                            val = h[0] / 255.0
                            if val < FALLBACK_SAMPLE_RATE:
                                run_deep = True
                                LOG.debug("fallback-sampled %s (val=%.3f)", u, val)
                        if not run_deep:
                            LOG.debug("skip %s — url not candidate and not sampled", u)
                            stats["skipped"] += 1
                            return

                        # deep HTML check -> scoring
                        try:
                            score, details = det.score_article_page(html, url=u)
                        except Exception:
                            LOG.exception("detector failed for %s", u)
                            score, details = 0, {}

                        if score < 2:
                            LOG.debug("skip %s — deep-check failed (score=%d details=%s)", u, score, details)
                            stats["skipped"] += 1
                            return
                        else:
                            LOG.debug("accept %s — score=%d details=%s", u, score, details)

                        # extract title and article text
                        soup = BeautifulSoup(html, "lxml")
                        title = (soup.title.string.strip() if soup.title and soup.title.string else "") or ""

                        raw_text = extract_text_from_html(html) or ""
                        # AI enrichment (summary + category) — optional
                        summary = None
                        category = None
                        if AI_ENABLED:
                            try:
                                summary = summarize_text(raw_text, max_sentences=3)
                            except Exception:
                                LOG.exception("summary failed for %s", u)
                                summary = ""
                            try:
                                category = classify_text(raw_text)
                            except Exception:
                                LOG.exception("classify failed for %s", u)
                                category = "other"

                        item = {
                            "url": u,
                            "title": title,
                            "published_at": dt.isoformat(),
                            "source": front,
                            "score": int(score),
                        }
                        if raw_text:
                            item["raw_text"] = raw_text[:20000]
                        if summary is not None:
                            item["summary"] = summary
                        if category is not None:
                            item["category"] = category
                        results.append(item)
                        stats["accepted"] += 1
                        if is_url_candidate:
                            stats["accepted_by_url"] += 1
                        else:
                            stats["accepted_by_fallback"] += 1
                tasks.append(asyncio.create_task(_proc()))
            if tasks:
                await asyncio.gather(*tasks)

        site_tasks = [process_site(f) for f in frontpages]
        await asyncio.gather(*site_tasks)
    LOG.info("found %d today articles (candidates=%d accepted=%d url_accepted=%d fallback_accepted=%d skipped=%d)", len(results), stats.get("candidates"), stats.get("accepted"), stats.get("accepted_by_url"), stats.get("accepted_by_fallback"), stats.get("skipped"))
    return results
