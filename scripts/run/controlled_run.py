#!/usr/bin/env python3
"""Controlled AI-layer test runner.

Собирает примеры из `data/processed/example_*.json`, скачивает до N страниц,
извлекает текст и выполняет параллельную summarization+classification,
замеряет время и сохраняет результаты.
"""
from __future__ import annotations
import argparse
import asyncio
import glob
import json
import logging
import os
import time
from typing import List

import httpx
from urllib.parse import urlparse
from bs4 import BeautifulSoup

from app.backend.services.ai_enrichment import extract_text_from_html, summarize_text, classify_text

LOG = logging.getLogger("controlled_run")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

HEADERS = {"User-Agent": "pdads_ai_test/1.0 (+https://example)"}
FETCH_TIMEOUT = 15.0


async def fetch_htmls(urls: List[str], concurrency: int = 8) -> List[dict]:
    sem = asyncio.Semaphore(concurrency)
    results: List[dict] = [None] * len(urls)
    async with httpx.AsyncClient(follow_redirects=True, headers=HEADERS) as client:
        async def _fetch(i: int, u: str):
            async with sem:
                try:
                    r = await client.get(u, timeout=FETCH_TIMEOUT)
                    # capture final URL, status and body (follow_redirects=True)
                    final = str(r.url) if r is not None else None
                    status = r.status_code if r is not None else None
                    text = r.text if r is not None else None
                    results[i] = {"original_url": u, "final_url": final, "html": text, "status": status}
                except Exception as e:
                    LOG.debug("fetch failed %s: %s", u, e)
                    results[i] = {"original_url": u, "final_url": None, "html": None, "status": None}

        tasks = [asyncio.create_task(_fetch(i, u)) for i, u in enumerate(urls)]
        await asyncio.gather(*tasks)
    return results


def _normalize_netloc(netloc: str) -> str:
    n = (netloc or "").lower()
    if n.startswith("www."):
        return n[4:]
    return n


def is_redirected_to_home(original_url: str, final_url: str) -> bool:
    if not final_url:
        return False
    try:
        o = urlparse(original_url)
        f = urlparse(final_url)
    except Exception:
        return False
    if _normalize_netloc(o.netloc) != _normalize_netloc(f.netloc):
        return False
    # final path empty or root -> homepage
    fp = (f.path or "").rstrip("/")
    return fp == ""


def is_invalid_redirect(original: str, final: str) -> bool:
    if not final:
        return False
    try:
        o = urlparse(original)
        f = urlparse(final)
    except Exception:
        return False
    return len(f.path or "") < len(o.path or "")


def is_homepage(soup: BeautifulSoup) -> bool:
    try:
        links = len(soup.find_all("a"))
        paragraphs = len([p for p in soup.find_all("p") if p.get_text(strip=True)])
        return links > 100 and paragraphs < 10
    except Exception:
        return False


async def parallel_summarize(items: List[dict], max_sentences: int = 3, concurrency: int = 8) -> List[dict]:
    loop = asyncio.get_event_loop()
    sem = asyncio.Semaphore(concurrency)

    async def _enrich(it: dict):
        async with sem:
            text = it.get("raw_text") or ""
            # run summarization in thread pool to allow parallel OpenAI calls
            summary = await loop.run_in_executor(None, summarize_text, text, max_sentences)
            # classification is cheap; run in executor as well to keep consistent
            category = await loop.run_in_executor(None, classify_text, text)
            it["summary"] = (summary or "").strip()
            it["category"] = category or "other"
            print(f"[AI] {it.get('title','')[:50]} -> {it['category']}")
            return it

    enriched = await asyncio.gather(*[_enrich(it) for it in items])
    return enriched


def load_example_urls(limit: int) -> List[str]:
    files = glob.glob("data/processed/example_*.json")
    seen = set()
    urls = []
    for f in files:
        try:
            with open(f, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            for it in data:
                u = it.get("url")
                if not u:
                    continue
                if u in seen:
                    continue
                seen.add(u)
                urls.append(u)
                if len(urls) >= limit:
                    return urls
        except Exception:
            LOG.exception("failed reading %s", f)
    return urls


async def main_async(limit: int, concurrency: int, out_path: str, examples: int, max_sentences: int):
    urls = load_example_urls(limit)
    if not urls:
        LOG.error("no example URLs found in data/processed/example_*.json")
        return 1
    LOG.info("will process %d urls (concurrency=%d)", len(urls), concurrency)

    start_fetch = time.perf_counter()
    fetched = await fetch_htmls(urls, concurrency=concurrency)
    fetch_time = time.perf_counter() - start_fetch
    LOG.info("fetched %d pages in %.2f sec", len(urls), fetch_time)

    items = []
    for entry in fetched:
        u = entry.get("original_url")
        final = entry.get("final_url")
        h = entry.get("html")
        raw_text = ""
        title = ""
        if not h:
            raw_text = ""
        else:
            # redirect checks
            if is_redirected_to_home(u, final):
                LOG.info("skipping %s because redirected to homepage %s", u, final)
                raw_text = ""
            elif is_invalid_redirect(u, final):
                LOG.info("skipping %s because invalid redirect to %s", u, final)
                raw_text = ""
            else:
                try:
                    soup = BeautifulSoup(h, "lxml")
                except Exception:
                    soup = BeautifulSoup(h, "html.parser")

                if is_homepage(soup):
                    LOG.info("skipping %s because page looks like homepage", u)
                    raw_text = ""
                else:
                    # pass final_url when available for domain-aware extraction
                    raw_text = extract_text_from_html(h, final or u)

            # lightweight title extraction
            try:
                soup_t = BeautifulSoup(h, "lxml")
                title = (soup_t.title.string.strip() if soup_t.title and soup_t.title.string else "") or ""
            except Exception:
                title = ""

        items.append({"url": u, "title": title, "raw_text": raw_text})

    # run parallel summarization
    start_ai = time.perf_counter()
    enriched = await parallel_summarize(items, max_sentences=max_sentences, concurrency=concurrency)
    ai_time = time.perf_counter() - start_ai
    LOG.info("AI enrichment done: %.2f sec for %d items (%.2f sec/item)", ai_time, len(enriched), ai_time / max(1, len(enriched)))

    # basic validations
    non_empty = sum(1 for it in enriched if it.get("summary"))
    full_text_equal = sum(1 for it in enriched if it.get("summary") and it.get("raw_text") and it.get("summary") == it.get("raw_text"))
    categories = {}
    for it in enriched:
        c = it.get("category") or "other"
        categories[c] = categories.get(c, 0) + 1

    # save results
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(enriched, fh, ensure_ascii=False, indent=2)
    LOG.info("saved %d enriched items to %s", len(enriched), out_path)

    # print summary
    print("\n--- RUN SUMMARY ---")
    print(f"urls_processed={len(urls)} fetch_time={fetch_time:.2f}s ai_time={ai_time:.2f}s total_time={(fetch_time+ai_time):.2f}s")
    print(f"summaries_non_empty={non_empty} full_text_equal={full_text_equal}")
    print("categories:")
    for k, v in sorted(categories.items(), key=lambda x: -x[1]):
        print(f" - {k}: {v}")

    # show examples
    print("\n--- EXAMPLES ---")
    for it in enriched[:examples]:
        print("TITLE:", it.get("title") or it.get("url"))
        print("CATEGORY:", it.get("category"))
        s = (it.get("summary") or "").replace("\n", " ")
        print("SUMMARY:", s[:800])
        print("--\n")

    return 0


def main():
    parser = argparse.ArgumentParser(description="Controlled AI-layer test runner")
    parser.add_argument("--limit", type=int, default=25, help="Number of URLs to process")
    parser.add_argument("--concurrency", type=int, default=8, help="Concurrency for fetch+AI")
    parser.add_argument("--out", default="data/debug/parsed_today_ai_test.json", help="Output JSON path")
    parser.add_argument("--examples", type=int, default=3, help="How many examples to print")
    parser.add_argument("--max-sentences", type=int, default=3, help="Max sentences for summary")
    args = parser.parse_args()

    # ensure we don't accidentally run AI in the pipeline (we use example URLs)
    os.environ.setdefault("ENABLE_AI", "0")

    rc = asyncio.run(main_async(args.limit, args.concurrency, args.out, args.examples, args.max_sentences))
    raise SystemExit(rc)


if __name__ == "__main__":
    main()
