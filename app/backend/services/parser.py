from __future__ import annotations
from typing import Optional
import asyncio
import re

from app.backend.db import session as db_session
from app.backend.services.ingestion_service import create_raw_news
from app.backend.services.system_service import update_last_parsed_at


def clean_text(text: str) -> str:
    """Clean text from HTML tags and normalize whitespace.

    Args:
        text: Raw text that may contain HTML

    Returns:
        Clean text without HTML tags, with normalized whitespace
    """
    if not text:
        return ""

    from bs4 import BeautifulSoup

    # Remove HTML tags using BeautifulSoup
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)

    # Normalize whitespace (multiple spaces/newlines -> single space)
    text = re.sub(r'\s+', ' ', text)

    # Remove any remaining HTML entities or broken characters
    text = text.replace('&nbsp;', ' ')
    text = text.replace('&quot;', '"')
    text = text.replace('&amp;', '&')
    text = text.replace('&lt;', '<')
    text = text.replace('&gt;', '>')

    return text.strip()


async def run_parser_async(
    rss_sources: Optional[list[str]] = None,
    site_sources: Optional[list[str]] = None,
    per_rss_limit: int = 10,
    per_site_limit: int = 20,
    dry_run: bool = True,
) -> dict:
    """Run feed/site ingestion.

    - When `dry_run=True` the parser will collect links from provided
      `site_sources`/`rss_sources`, process them (detector + extraction) and
      return results without writing to DB. This is safe for local testing.

    - When `dry_run=False` the function delegates to `feed_fetcher.ingest_many`
      which will persist items to the DB using `create_raw_news`.
    """
    site_sources = site_sources or [
        "https://daryo.uz",
        "https://kun.uz",
        "https://gazeta.uz",
        "https://podrobno.uz",
        "https://uznews.uz",
    ]
    rss_sources = rss_sources or [
        "https://daryo.uz/rss",
        "https://gazeta.uz/ru/rss",
    ]

    # helper: collect links from a site frontpage
    async def _collect_site_links(base: str, limit: int) -> list[str]:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin, urlparse
        from app.backend.services.http_client import get_async_client

        client = await get_async_client()
        try:
            resp = await client.get(base)
            resp.raise_for_status()
            # Force UTF-8 encoding to handle Cyrillic correctly
            html = resp.content.decode("utf-8", errors="ignore")
        except Exception:
            return []
        # Parse with explicit UTF-8 encoding
        soup = BeautifulSoup(html, "html.parser", from_encoding="utf-8")
        anchors = soup.find_all("a", href=True)
        seen = set()
        links: list[str] = []
        for a in anchors:
            href = a.get("href")
            if not href:
                continue
            url = urljoin(base, href)
            if url in seen:
                continue
            seen.add(url)
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                continue
            # skip obvious non-article files
            if any(parsed.path.lower().endswith(ext) for ext in (".jpg", ".png", ".pdf", ".zip", ".json", ".css", ".js")):
                continue
            # domain check
            try:
                if urlparse(base).netloc.lower().removeprefix("www.") != parsed.netloc.lower().removeprefix("www."):
                    continue
            except Exception:
                pass
            links.append(url)
            if len(links) >= limit:
                break
        return links

    async def _fetch_ignore_session(_session, url: str) -> Optional[str]:
        from app.backend.services.http_client import get_async_client

        client = await get_async_client()
        try:
            resp = await client.get(url)
            resp.raise_for_status()
            # Force UTF-8 encoding to handle Cyrillic correctly
            return resp.content.decode("utf-8", errors="ignore")
        except Exception:
            return None

    if dry_run:
        # Lightweight dry-run: collect links and run article_processor without DB writes
        try:
            from bs4 import BeautifulSoup
            from urllib.parse import urljoin, urlparse
            from app.backend.services.http_client import get_async_client
            from app.backend.services.article_processor import process_all

            # reuse helpers declared above: _collect_site_links, _fetch_ignore_session

            # collect links across sites
            all_links: list[str] = []
            for s in site_sources:
                lst = await _collect_site_links(s, per_site_limit)
                all_links.extend(lst)

            # de-duplicate
            unique_links = list(dict.fromkeys(all_links))[: per_site_limit * len(site_sources)]

            # process pages with article_processor (no DB writes)
            processed, stats = await process_all(None, unique_links, _fetch_ignore_session, concurrency=8)
            return {"status": "ok", "processed_count": len(processed), "stats": stats, "sample": processed[:5]}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    # non-dry-run: SIMPLE ingestion — collect links, process each article and save
    import logging
    logger = logging.getLogger(__name__)
    
    async with db_session.SessionLocal() as session:
        try:
            from app.backend.services.article_processor import process_article
            from app.backend.services.http_client import get_async_client
            from app.backend.services.feed_fetcher import ingest_rss_feed

            client = await get_async_client()

            async def _fetch(_s, url: str) -> Optional[str]:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    # Force UTF-8 encoding to handle Cyrillic correctly
                    return resp.content.decode("utf-8", errors="ignore")
                except Exception as exc:
                    logger.warning("[PARSER] Failed to fetch %s: %s", url, exc)
                    return None

            total_saved = 0
            items_found = 0
            errors = []

            # Process RSS feeds first (if any)
            for rss_url in rss_sources:
                try:
                    logger.info("[PARSER] Processing RSS: %s", rss_url)
                    count = await ingest_rss_feed(session, rss_url, limit=per_rss_limit)
                    total_saved += count
                    logger.info("[PARSER] RSS %s saved: %s articles", rss_url, count)
                except Exception as e:
                    logger.exception("[PARSER] RSS failed %s: %s", rss_url, e)
                    try:
                        await session.rollback()
                    except Exception:
                        pass
                    errors.append(f"rss:{rss_url}:{e}")

            # Process site sources
            for s in site_sources:
                logger.info("[PARSER] Processing site: %s", s)
                links = await _collect_site_links(s, per_site_limit)
                logger.info("[PARSER] Site %s found %s links", s, len(links))
                if not links:
                    logger.warning("[DEBUG] EMPTY_LINKS source=%s", s)
                
                for url in links[:per_site_limit]:
                    try:
                        item, reason = await process_article(session, url, _fetch)
                        if not item:
                            logger.debug("[PARSER] Skipped %s: %s", url, reason)
                            continue

                        # Clean text before saving
                        title = clean_text(item.get("title") or "")
                        raw_text = clean_text(item.get("content") or "")
                        items_found += 1

                        payload = {
                            "title": title,
                            "raw_text": raw_text,
                            "source_url": item.get("source_url") or item.get("url"),
                            "image_url": item.get("image_url"),
                            "category": None,
                            "region": None,
                            "is_urgent": False,
                        }
                        print(f"[DEBUG] ITEM: {title}")
                        print(f"[DEBUG] ITEM image_url: {payload.get('image_url')}")

                        result = await create_raw_news(session, payload)
                        if result and result.get("id"):
                            total_saved += 1
                            logger.info("[PARSER] Saved raw_news id=%s: %s", result["id"], url)
                        else:
                            logger.warning("[PARSER] Duplicate or failed: %s", url)
                    except Exception as e:
                        logger.exception("[PARSER] Error processing %s: %s", url, e)
                        try:
                            await session.rollback()
                        except Exception:
                            pass
                        errors.append(f"{url}:{e}")

            # record parser heartbeat
            try:
                await update_last_parsed_at(session)
                logger.info("[PARSER] Heartbeat updated")
            except Exception:
                logger.warning("[PARSER] Failed to update last_parsed_at")

            print(f"[PARSER] saved {total_saved}")
            logger.info("[PARSER] saved %s", total_saved)
            print(f"[DEBUG] ITEMS FOUND: {items_found}")
            logger.info("[PARSER] Total saved: %s, errors: %s", total_saved, len(errors))
            return {"status": "ok", "saved": total_saved, "items_found": items_found, "errors": errors[:10]}
        except Exception as e:
            logger.exception("[PARSER] Fatal error: %s", e)
            return {"status": "error", "error": str(e)}


def run_parser(
    rss_sources: Optional[list[str]] = None,
    site_sources: Optional[list[str]] = None,
    per_rss_limit: int = 10,
    per_site_limit: int = 20,
    dry_run: bool = True,
) -> dict:
    """Synchronous wrapper for running the async parser from sync contexts.

    Typical usage from Celery tasks: uses asyncio.run() for proper async handling.
    """
    # FIX: Use asyncio.run() instead of manual loop management (production-safe)
    return asyncio.run(
        run_parser_async(
            rss_sources=rss_sources,
            site_sources=site_sources,
            per_rss_limit=per_rss_limit,
            per_site_limit=per_site_limit,
            dry_run=dry_run,
        )
    )


__all__ = ["run_parser", "run_parser_async"]
