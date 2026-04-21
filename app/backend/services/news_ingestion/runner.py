from __future__ import annotations

import asyncio
import time
import argparse
from typing import List

from app.backend.core.config import settings
from app.backend.services.news_ingestion.global_fetcher import fetch_global_news
from app.backend.services.news_ingestion.regional_fetcher import fetch_regional_news
from app.backend.services.news_ingestion.deduplicator import generate_hash
from app.backend.services.news_ingestion.saver import save_batch


GLOBAL_QUERIES = ["AI", "technology", "world news"]


async def run_pipeline(save: bool = False, verbose: bool = False) -> dict:
    start = time.perf_counter()
    # fetch both concurrently
    global_coro = fetch_global_news(
        GLOBAL_QUERIES, page_size=12, api_key=(settings.NEWS_API_KEY or None), verbose=verbose
    )
    regional_coro = fetch_regional_news(verbose=verbose)
    global_news, regional_news = await asyncio.gather(global_coro, regional_coro)

    total_before = len(global_news) + len(regional_news)

    # merge and dedupe by generated hash
    seen = set()
    unique: List[dict] = []
    for a in [*global_news, *regional_news]:
        h = generate_hash(a.get("title"), a.get("content"))
        if h in seen:
            continue
        seen.add(h)
        unique.append(a)

    fetch_time = time.perf_counter() - start

    if verbose:
        print(f"[runner] NEWS_API_KEY set: {bool(settings.NEWS_API_KEY and settings.NEWS_API_KEY.strip())}")
        print(f"[runner] global fetched: {len(global_news)}; regional fetched: {len(regional_news)}")
        if global_news:
            print("[runner] sample global titles:", [a.get("title") for a in global_news[:5]])
        if regional_news:
            print("[runner] sample regional titles:", [a.get("title") for a in regional_news[:5]])

    # dry-run unless save=True
    result = await save_batch(unique, dry_run=not save)

    return {
        "global_count": len(global_news),
        "regional_count": len(regional_news),
        "total_before_dedup": total_before,
        "total_after_dedup": len(unique),
        "fetch_seconds": round(fetch_time, 2),
        "save_result": result,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser("news_ingest_runner")
    parser.add_argument("--save", action="store_true", help="Persist to DB (off by default - dry run)")
    parser.add_argument("--verbose", action="store_true", help="Print debug information")
    args = parser.parse_args()

    res = asyncio.run(run_pipeline(save=args.save, verbose=args.verbose))
    print("RESULT:")
    for k, v in res.items():
        print(f"{k}: {v}")
