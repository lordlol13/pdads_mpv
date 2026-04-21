#!/usr/bin/env python3
"""Verbose processor: collects links and records per-URL outcomes (processed + skipped).

Saves `data/debug/run_details_limit{limit}.json` with arrays `processed` and `skipped`.
"""
from __future__ import annotations
import asyncio
import time
import json
from typing import List
import argparse

import httpx
from bs4 import BeautifulSoup

from app.backend.services.today_pipeline_utils import extract_links, USER_AGENT, REQUEST_TIMEOUT
from app.backend.services.article_processor import process_article
from app.backend.services.ai_enrichment import summarize_text, classify_text
from app.backend.services.content_extractors import extract_by_domain
from app.backend.services.site_parsers import parse_article_by_domain
from app.backend.services.sources import SOURCES


FRONTPAGES: List[str] = list(SOURCES.values())

DEFAULT_LIMIT = 50
CONCURRENCY = 6


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

        processed = []
        skipped = []

        # process sequentially to preserve order and capture reasons clearly
        for u in links[:limit]:
            try:
                item, reason = await process_article(client, u, fetch)
            except Exception as e:
                item, reason = None, f"exception:{e}"

            # fetch html and pre-filter content for inspection
            html = await fetch(client, u)
            title = None
            content_pre = None
            if html:
                try:
                    soup = BeautifulSoup(html, "lxml")
                except Exception:
                    soup = BeautifulSoup(html, "html.parser")
                try:
                    parsed = parse_article_by_domain(html, u)
                    title = parsed.get("title") or ""
                except Exception:
                    title = (soup.title.string.strip() if soup.title and soup.title.string else "")
                try:
                    content_pre = extract_by_domain(u, soup) or ""
                except Exception:
                    content_pre = ""

            if item:
                content_snippet = (item.get("content") or content_pre or "")[:1000]
                summary = summarize_text(item.get("content") or content_pre or "", max_sentences=3)
                category = classify_text(item.get("content") or content_pre or "")
                suspicious = False
                if len(content_snippet) < 400:
                    suspicious = True
                low = content_snippet.lower()
                for ph in ("izoh qoldirish", "guvohnoma", "reklam", "aksiya", "©"):
                    if ph in low:
                        suspicious = True
                        break

                processed.append({
                    "url": u,
                    "title": title or item.get("title") or "",
                    "summary": summary,
                    "category": category,
                    "content_snippet": content_snippet,
                    "suspicious": suspicious,
                })
            else:
                skipped.append({
                    "url": u,
                    "reason": reason,
                    "title": title or "",
                    "content_snippet": (content_pre or "")[:1000],
                })

        t1 = time.time()

        out = {
            "total_time": t1 - t0,
            "processed_count": len(processed),
            "skipped_count": len(skipped),
            "processed": processed,
            "skipped": skipped,
            "requested_limit": limit,
            "collected_links": len(links),
        }

        out_path = f"data/debug/run_details_limit{limit}.json"
        with open(out_path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=2)

        print("[DETAILS SAVED]", out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="Number of links to process")
    args = parser.parse_args()
    asyncio.run(main(args.limit))
