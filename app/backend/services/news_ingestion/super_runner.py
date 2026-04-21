from __future__ import annotations

import argparse
import asyncio
import time
from typing import Any, Dict, List, Optional

from app.backend.core.config import settings
from app.backend.services.http_client import get_async_client
from app.backend.services.news_ingestion.global_fetcher import fetch_newsapi, extract_article
from app.backend.services.news_ingestion.regional_fetcher import fetch_regional_news
from app.backend.services.news_ingestion.deduplicator import generate_hash
from app.backend.services.news_ingestion.saver import save_batch


DEFAULT_GLOBAL_QUERIES = ["AI", "technology", "world news"]


async def fetch_newsapi_candidates(
    queries: List[str], page_size: int = 12, api_key: Optional[str] = None, verbose: bool = False
) -> List[Dict[str, str]]:
    client = await get_async_client()
    tasks = [fetch_newsapi(client, q, page_size=page_size, api_key=api_key) for q in queries]
    batches = await asyncio.gather(*tasks)

    seen = set()
    candidates: List[Dict[str, str]] = []
    for batch in batches:
        for art in (batch or []):
            url = (art.get("url") or "").strip()
            if not url:
                continue
            if url in seen:
                continue
            seen.add(url)
            candidates.append({"url": url, "title": art.get("title") or ""})

    if verbose:
        print(f"[super_runner] newsapi candidates={len(candidates)} from queries={len(queries)}")
    return candidates


async def parse_global_candidates(
    candidates: List[Dict[str, str]], concurrency: int = 8, verbose: bool = False
) -> List[Dict[str, Any]]:
    client = await get_async_client()
    sem = asyncio.Semaphore(concurrency)

    async def _parse(item: Dict[str, str]) -> Optional[Dict[str, Any]]:
        url = item.get("url")
        title = item.get("title") or ""
        async with sem:
            text = await extract_article(client, url, verbose=verbose)
            if not text:
                if verbose:
                    print(f"[super_runner] skipped global {url} — extraction empty")
                return None
            return {"title": title, "content": text, "source_url": url, "image_url": None, "source_type": "global"}

    tasks = [asyncio.create_task(_parse(c)) for c in candidates]
    results: List[Dict[str, Any]] = []
    for fut in asyncio.as_completed(tasks):
        res = await fut
        if res:
            results.append(res)
    return results


async def run_super_runner(
    save: bool = False,
    verbose: bool = False,
    concurrency: int = 8,
    per_source_limit: int = 8,
    page_size: int = 12,
    queries: Optional[List[str]] = None,
) -> Dict[str, Any]:
    queries = queries or DEFAULT_GLOBAL_QUERIES
    start = time.perf_counter()

    # 1) Get NewsAPI candidates (only links + title)
    newsapi_candidates = await fetch_newsapi_candidates(queries, page_size=page_size, api_key=(settings.NEWS_API_KEY or None), verbose=verbose)

    # 2) Parse global candidates through extractor (NO fallback to NewsAPI 'content')
    parsed_global = []
    if newsapi_candidates:
        parsed_global = await parse_global_candidates(newsapi_candidates, concurrency=concurrency, verbose=verbose)

    # 3) Fetch regional articles directly (they are expected to contain content)
    regional_articles = await fetch_regional_news(per_source_limit=per_source_limit, verbose=verbose)

    total_before = len(parsed_global) + len(regional_articles)

    # 4) In-run dedupe by generated hash
    seen = set()
    unique: List[Dict[str, Any]] = []
    for a in [*parsed_global, *regional_articles]:
        h = generate_hash(a.get("title"), a.get("content"))
        if h in seen:
            if verbose:
                print(f"[super_runner] duplicate in-run skipped: {a.get('source_url')}")
            continue
        seen.add(h)
        unique.append(a)

    # 5) Save (dry-run by default)
    if verbose:
        print("[super_runner] Articles before save:")
        for a in unique:
            title = (a.get("title") or "")[:60]
            url = a.get("source_url")
            content = a.get("content") or ""
            img = a.get("image_url")
            print(f"[ARTICLE] {title}")
            print(f"URL: {url}")
            print(f"CONTENT LEN: {len(content)}")
            print(f"IMAGE: {img}")
            print("-"*50)

    save_result = await save_batch(unique, dry_run=not save)

    elapsed = time.perf_counter() - start
    return {
        "global_candidates": len(newsapi_candidates),
        "parsed_global": len(parsed_global),
        "regional": len(regional_articles),
        "total_before_dedup": total_before,
        "total_after_dedup": len(unique),
        "fetch_seconds": round(elapsed, 2),
        "save_result": save_result,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser("super_news_ingest")
    parser.add_argument("--save", action="store_true", help="Persist to DB (off by default - dry run)")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--concurrency", type=int, default=8, help="Concurrent parser workers for global links")
    parser.add_argument("--per-source-limit", type=int, default=8, help="Per-regional-source link limit")
    parser.add_argument("--page-size", type=int, default=12, help="NewsAPI page size per query")
    args = parser.parse_args()

    res = asyncio.run(
        run_super_runner(
            save=args.save,
            verbose=args.verbose,
            concurrency=args.concurrency,
            per_source_limit=args.per_source_limit,
            page_size=args.page_size,
        )
    )

    print("RESULT:")
    for k, v in res.items():
        print(f"{k}: {v}")
