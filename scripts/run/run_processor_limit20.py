#!/usr/bin/env python3
"""Quick runner: collect links from frontpages, process up to 20 articles using article_processor.

Saves `data/debug/run_results_limit{limit}.json` with timing and samples.
"""
from __future__ import annotations
import asyncio
import time
import json
from typing import List
import argparse

import httpx

from app.backend.services.today_pipeline_utils import extract_links, USER_AGENT, REQUEST_TIMEOUT
from app.backend.services.article_processor import process_all
from app.backend.services.ai_enrichment import summarize_text, classify_text
from app.backend.services.sources import SOURCES


FRONTPAGES: List[str] = list(SOURCES.values())

DEFAULT_LIMIT = 20
CONCURRENCY = 8


async def fetch(session: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await session.get(url, timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


async def main(limit: int):
    headers = {"User-Agent": USER_AGENT}
    async with httpx.AsyncClient(headers=headers, follow_redirects=True) as client:
        # collect links
        seen = set()
        links: List[str] = []
        for front in FRONTPAGES:
            ls = await extract_links(client, front, max_links=200)
            for l in ls:
                if l not in seen:
                    seen.add(l)
                    links.append(l)
                if len(links) >= limit:
                    break
            if len(links) >= limit:
                break

        print(f"[RUN] collected {len(links)} links, proceeding with limit={limit}")

        t0 = time.time()
        results, stats = await process_all(client, links[:limit], fetch, concurrency=CONCURRENCY)
        t1 = time.time()

        total_time = t1 - t0
        articles_processed = len(results)
        time_per_article = total_time / articles_processed if articles_processed else None

        samples = []
        for r in results[:5]:
            url = r.get("url")
            title = r.get("title") or ""
            content = r.get("content") or ""
            summary = summarize_text(content, max_sentences=3)
            category = classify_text(content)
            samples.append({
                "url": url,
                "title": title,
                "summary": summary,
                "category": category,
                "raw_text_snippet": content[:500],
            })

        out = {
            "total_time": total_time,
            "articles_processed": articles_processed,
            "time_per_article": time_per_article,
            "samples": samples,
            "stats": stats,
            "requested_limit": limit,
            "collected_links": len(links),
        }

        out_path = f"data/debug/run_results_limit{limit}.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)

        print("[RESULT]", json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Number of links to process")
    args = parser.parse_args()
    asyncio.run(main(args.limit))
