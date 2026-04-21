from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any, Dict, List, Optional

from app.backend.core.config import settings
from app.backend.services.http_client import get_async_client
from app.backend.services.news_ingestion.global_fetcher import fetch_newsapi
from app.backend.services.news_ingestion.regional_fetcher import fetch_regional_news
from app.backend.services.news_ingestion.deduplicator import generate_hash
from app.backend.services.news_ingestion.saver import save_batch
from app.backend.services.ingestion_service import _normalize_source_url


DEFAULT_GLOBAL_QUERIES = ["AI", "technology", "world news"]

DEFAULT_REGIONAL_SOURCES = [
    "https://daryo.uz",
    "https://kun.uz",
    "https://www.gazeta.uz/ru/",
    "https://uznews.uz",
    "https://podrobno.uz",
    "https://nova24.uz",
]


async def fetch_global_light(queries: List[str], page_size: int, api_key: Optional[str], verbose: bool = False) -> List[Dict[str, Any]]:
    if not api_key:
        if verbose:
            print("[hybrid_runner] NEWS_API_KEY not set; skipping global fetch")
        return []

    client = await get_async_client()
    tasks = [fetch_newsapi(client, q, page_size=page_size, api_key=api_key) for q in queries]
    batches = await asyncio.gather(*tasks)

    results: List[Dict[str, Any]] = []
    seen = set()
    for batch in batches:
        for art in (batch or []):
            url = (art.get("url") or "").strip()
            if not url or url in seen:
                continue
            seen.add(url)
            results.append(
                {
                    "title": art.get("title") or "",
                    "content": art.get("description") or art.get("content") or "",
                    "source_url": url,
                    "image_url": art.get("urlToImage") or art.get("image"),
                    "source_type": "global",
                    "published_at": art.get("publishedAt"),
                }
            )

    if verbose:
        print(f"[hybrid_runner] global_light candidates={len(results)}")
    return results


async def run_hybrid(
    save: bool = False,
    verbose: bool = False,
    page_size: int = 10,
    per_source_limit: int = 2,
    queries: Optional[List[str]] = None,
    regional_sources: Optional[List[str]] = None,
) -> Dict[str, Any]:
    queries = queries or DEFAULT_GLOBAL_QUERIES
    regional_sources = regional_sources or DEFAULT_REGIONAL_SOURCES

    start = time.perf_counter()

    # Launch both tasks: global lightweight + regional full parser
    g_task = asyncio.create_task(fetch_global_light(queries, page_size=page_size, api_key=(settings.NEWS_API_KEY or None), verbose=verbose))
    r_task = asyncio.create_task(fetch_regional_news(sources=regional_sources, per_source_limit=per_source_limit, verbose=verbose))

    global_news, regional_news = await asyncio.gather(g_task, r_task)

    if verbose:
        print(f"[hybrid_runner] GLOBAL: {len(global_news)}; REGIONAL: {len(regional_news)}")

    all_news = [*global_news, *regional_news]

    # Dedupe by normalized source_url first, fall back to content hash when no URL
    seen_urls = set()
    seen_hash = set()
    unique: List[Dict[str, Any]] = []
    for a in all_news:
        raw_url = a.get("source_url") or ""
        norm = _normalize_source_url(raw_url)
        if norm:
            if norm in seen_urls:
                if verbose:
                    print(f"[hybrid_runner] dup url skipped: {norm}")
                continue
            seen_urls.add(norm)
            unique.append(a)
        else:
            h = generate_hash(a.get("title"), a.get("content"))
            if h in seen_hash:
                if verbose:
                    print(f"[hybrid_runner] dup hash skipped: {h[:8]}")
                continue
            seen_hash.add(h)
            unique.append(a)

    if verbose:
        print(f"[hybrid_runner] AFTER DEDUP: {len(unique)}")

    # Debug print per article
    if verbose:
        print("[hybrid_runner] Articles prepared for save:")
        for a in unique:
            title = (a.get("title") or "")[:80]
            url = a.get("source_url")
            content = a.get("content") or ""
            img = a.get("image_url")
            print(f"[ARTICLE] {title}")
            print(f"URL: {url}")
            print(f"CONTENT LEN: {len(content)}")
            print(f"IMAGE: {img}")
            print("-" * 50)

    save_result = await save_batch(unique, dry_run=not save)

    elapsed = time.perf_counter() - start
    return {
        "global_count": len(global_news),
        "regional_count": len(regional_news),
        "after_dedup": len(unique),
        "fetch_seconds": round(elapsed, 2),
        "save_result": save_result,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser("hybrid_ingest")
    parser.add_argument("--save", action="store_true", help="Persist to DB (off by default - dry run)")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--page-size", type=int, default=10, help="NewsAPI page size per query")
    parser.add_argument("--per-source-limit", type=int, default=2, help="Per regional source link limit")
    parser.add_argument("--regional-sources", type=str, default=",")
    args = parser.parse_args()

    reg_sources = args.regional_sources.split(",") if args.regional_sources and args.regional_sources.strip() else None

    res = asyncio.run(
        run_hybrid(
            save=args.save,
            verbose=args.verbose,
            page_size=args.page_size,
            per_source_limit=args.per_source_limit,
            regional_sources=reg_sources,
        )
    )

    print("RESULT:")
    for k, v in res.items():
        print(f"{k}: {v}")
