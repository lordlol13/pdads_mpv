"""Dry-run ingest: fetch articles but don't write to DB.

This script monkeypatches `create_raw_news` to a no-op that prints
extracted payloads, then calls `ingest_many` with small limits.
"""
from __future__ import annotations

import asyncio
import sys

from app.backend.services import feed_fetcher
from app.backend.services import ingestion_service


async def _fake_create_raw_news(session, payload):
    title = (payload.get("title") or "")
    src = payload.get("source_url")
    print("DRY-RAW-NEWS:", title[:120], "->", src)
    # return something resembling the real result
    return {"id": None, **payload}


async def main():
    # Monkeypatch DB writer to avoid mutations during dry-run
    ingestion_service.create_raw_news = _fake_create_raw_news
    # feed_fetcher imported the function directly, patch there as well
    try:
        feed_fetcher.create_raw_news = _fake_create_raw_news
    except Exception:
        pass

    rss = [
        "https://gazeta.uz/ru/rss",
        "https://daryo.uz/rss",
    ]
    sites = [
        "https://uz24.uz",
        "https://kun.uz",
    ]

    print("Starting dry-run ingest (no DB writes).")
    summary = await feed_fetcher.ingest_many(None, rss_sources=rss, site_sources=sites, per_rss_limit=2, per_site_limit=3)
    print("Dry-run summary:", summary)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(1)
