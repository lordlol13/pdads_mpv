from __future__ import annotations
from typing import Optional
import asyncio

from app.backend.db.session import SessionLocal
from app.backend.services.ingestion_service import create_raw_news
from app.backend.services.system_service import update_last_parsed_at


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
            html = resp.text
        except Exception:
            return []
        soup = BeautifulSoup(html, "html.parser")
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
            return resp.text
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
    async with SessionLocal() as session:
        try:
            from app.backend.services.article_processor import process_article
            from app.backend.services.http_client import get_async_client

            client = await get_async_client()

            async def _fetch(_s, url: str) -> Optional[str]:
                try:
                    resp = await client.get(url)
                    resp.raise_for_status()
                    return resp.text
                except Exception:
                    return None

            total_saved = 0
            for s in site_sources:
                links = await _collect_site_links(s, per_site_limit)
                for url in links[:per_site_limit]:
                    try:
                        item, reason = await process_article(session, url, _fetch)
                        if not item:
                            continue

                        payload = {
                            "title": item.get("title") or "",
                            "raw_text": item.get("content"),
                            "source_url": item.get("url"),
                            "image_url": None,
                            "category": None,
                            "region": None,
                            "is_urgent": False,
                        }

                        await create_raw_news(session, payload)
                        total_saved += 1
                    except Exception as e:
                        print(f"[ERROR] {url} -> {e}")

            # record parser heartbeat
            try:
                await update_last_parsed_at(session)
            except Exception:
                # Don't fail the whole run if heartbeat update fails; log to stdout for visibility
                print("[WARN] failed to update last_parsed_at")

            return {"status": "ok", "saved": total_saved}
        except Exception as e:
            return {"status": "error", "error": str(e)}


def run_parser(
    rss_sources: Optional[list[str]] = None,
    site_sources: Optional[list[str]] = None,
    per_rss_limit: int = 10,
    per_site_limit: int = 20,
    dry_run: bool = True,
) -> dict:
    """Synchronous wrapper for running the async parser from sync contexts.

    Typical usage from Celery tasks: create a new event loop and call this
    wrapper so DB async engine/session are used inside the task.
    """
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(
            run_parser_async(
                rss_sources=rss_sources,
                site_sources=site_sources,
                per_rss_limit=per_rss_limit,
                per_site_limit=per_site_limit,
                dry_run=dry_run,
            )
        )
    finally:
        try:
            loop.close()
        except Exception:
            pass


__all__ = ["run_parser", "run_parser_async"]
