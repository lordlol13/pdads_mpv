#!/usr/bin/env python3
import asyncio
import httpx
from app.backend.services.news_api_service import _parse_rss_payload

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/115.0.0.0 Safari/537.36"
)

async def fetch(url: str):
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=20.0, follow_redirects=True) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            return r.text
        except Exception as e:
            return f"__ERROR__: {e}"

async def try_variants(name: str, domain: str, variants: list[str]):
    print(f"\nChecking {name} ({domain})")
    for v in variants:
        url = v if v.startswith("http") else f"https://{domain.rstrip('/')}/{v.lstrip('/')}"
        text = await fetch(url)
        if isinstance(text, str) and text.startswith("__ERROR__:"):
            print(f" {url} -> ERROR: {text[10:70]}")
            continue
        if not text or (isinstance(text, str) and ('<item' not in text.lower() and '<entry' not in text.lower())):
            # not an rss/atom payload
            print(f" {url} -> no feed markers")
            continue
        items = _parse_rss_payload(text, name, 100)
        print(f" {url} -> {len(items)} items")
        for it in items[:5]:
            print(f"   - {it.get('title')[:120]} — {it.get('url')}")
        # once we find a working feed, stop
        break

async def main():
    sites = [
        ("Gazeta.uz", "www.gazeta.uz", ["ru/rss", "rss", "ru/rss.xml", "rss.xml", "ru/feed"]),
        ("Daryo", "daryo.uz", ["rss", "feed", "rss.xml", "feed.xml", "feeds" , "ru/rss"]),
    ]
    for name, domain, variants in sites:
        await try_variants(name, domain, variants)

if __name__ == '__main__':
    asyncio.run(main())
