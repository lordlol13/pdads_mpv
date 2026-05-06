from __future__ import annotations

import asyncio
import logging
import re
from typing import Optional

from app.backend.core.config import settings
from app.backend.db import session as db_session
from app.backend.services.ingestion_service import create_raw_news
from app.backend.services.system_service import update_last_parsed_at


logger = logging.getLogger(__name__)


def clean_text(text: str) -> str:
    """Clean text from HTML tags and normalize whitespace."""
    if not text:
        return ""

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text(separator=" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    text = text.replace("&nbsp;", " ")
    text = text.replace("&quot;", '"')
    text = text.replace("&amp;", "&")
    text = text.replace("&lt;", "<")
    text = text.replace("&gt;", ">")
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
      return results without writing to DB.

    - When `dry_run=False` the function delegates to `feed_fetcher.ingest_many`
      which will persist items to the DB using `create_raw_news`.
    """
    logger.info("[INGESTION] started")
    logger.info(f"[DB] using: {settings.DATABASE_URL}")

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

    async def _collect_site_links(base: str, limit: int) -> list[str]:
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin, urlparse
        from app.backend.services.http_client import get_async_client

        client = await get_async_client()
        try:
            resp = await client.get(base)
            resp.raise_for_status()
            html = resp.content.decode("utf-8", errors="ignore")
        except Exception:
            return []

        soup = BeautifulSoup(html, "html.parser", from_encoding="utf-8")
        anchors = soup.find_all("a", href=True)
        seen: set[str] = set()
        links: list[str] = []

        for anchor in anchors:
            href = anchor.get("href")
            if not href:
                continue
            url = urljoin(base, href)
            if url in seen:
                continue
            seen.add(url)

            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                continue
            if any(parsed.path.lower().endswith(ext) for ext in (".jpg", ".png", ".pdf", ".zip", ".json", ".css", ".js")):
                continue
            try:
                base_host = urlparse(base).netloc.lower().removeprefix("www.")
                item_host = parsed.netloc.lower().removeprefix("www.")
                if base_host != item_host:
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
            return resp.content.decode("utf-8", errors="ignore")
        except Exception:
            return None

    if dry_run:
        try:
            from app.backend.services.article_processor import process_all

            all_links: list[str] = []
            for source in site_sources:
                all_links.extend(await _collect_site_links(source, per_site_limit))

            unique_links = list(dict.fromkeys(all_links))[: per_site_limit * len(site_sources)]
            processed, stats = await process_all(None, unique_links, _fetch_ignore_session, concurrency=8)
            return {"status": "ok", "processed_count": len(processed), "stats": stats, "sample": processed[:5]}
        except Exception as exc:
            return {"status": "error", "error": str(exc)}

    async with db_session.SessionLocal() as session:
        try:
            from app.backend.services.article_processor import process_article
            from app.backend.services.http_client import get_async_client
            from app.backend.services.feed_fetcher import ingest_rss_feed

            client = await get_async_client()

            async def _fetch(_session, url: str) -> Optional[str]:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return resp.content.decode("utf-8", errors="ignore")
                except Exception as exc:
                    logger.warning(f"[PARSER] Failed to fetch {url}: {exc}")
                    return None

            total_saved = 0
            items_found = 0
            errors: list[str] = []

            for rss_url in rss_sources:
                try:
                    logger.info(f"[PARSER] Processing RSS: {rss_url}")
                    count = await ingest_rss_feed(session, rss_url, limit=per_rss_limit)
                    total_saved += count
                    logger.info(f"[PARSER] RSS {rss_url} saved: {count} articles")
                except Exception as exc:
                    logger.exception(f"[PARSER] RSS failed {rss_url}: {exc}")
                    try:
                        await session.rollback()
                    except Exception:
                        pass
                    errors.append(f"rss:{rss_url}:{exc}")

            for source in site_sources:
                logger.info(f"[PARSER] Processing site: {source}")
                links = await _collect_site_links(source, per_site_limit)
                logger.info(f"[PARSER] Site {source} found {len(links)} links")
                logger.info(f"[INGESTION] fetched items count={len(links)}")

                if not links:
                    logger.warning(f"[DEBUG] EMPTY_LINKS source={source}")

                for url in links[:per_site_limit]:
                    try:
                        item, reason = await process_article(session, url, _fetch)
                        if not item:
                            logger.debug(f"[PARSER] Skipped {url}: {reason}")
                            continue

                        title = clean_text(item.get("title") or "")
                        raw_text = clean_text(item.get("content") or "")
                        items_found += 1
                        logger.info(f"[INGESTION] processing url={item.get('source_url') or item.get('url') or url}")

                        payload = {
                            "title": title,
                            "raw_text": raw_text,
                            "source_url": item.get("source_url") or item.get("url"),
                            "image_url": item.get("image_url"),
                            "category": None,
                            "region": None,
                            "is_urgent": False,
                        }

                        result = await create_raw_news(session, payload)
                        if result and result.get("id"):
                            total_saved += 1
                            logger.info(f"[PARSER] Saved raw_news id={result['id']}: {url}")
                        else:
                            logger.warning(f"[PARSER] Duplicate or failed: {url}")
                    except Exception as exc:
                        logger.exception(f"[PARSER] Error processing {url}: {exc}")
                        try:
                            await session.rollback()
                        except Exception:
                            pass
                        errors.append(f"{url}:{exc}")

            try:
                await update_last_parsed_at(session)
                logger.info("[PARSER] Heartbeat updated")
            except Exception:
                logger.warning("[PARSER] Failed to update last_parsed_at")

            logger.info(f"[PARSER] saved {total_saved}")
            logger.info(f"[PARSER] Total saved: {total_saved}, errors: {len(errors)}")
            return {"status": "ok", "saved": total_saved, "items_found": items_found, "errors": errors[:10]}
        except Exception as exc:
            logger.exception(f"[PARSER] Fatal error: {exc}")
            return {"status": "error", "error": str(exc)}


def run_parser(
    rss_sources: Optional[list[str]] = None,
    site_sources: Optional[list[str]] = None,
    per_rss_limit: int = 10,
    per_site_limit: int = 20,
    dry_run: bool = True,
) -> dict:
    """Synchronous wrapper for running the async parser from sync contexts."""
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
