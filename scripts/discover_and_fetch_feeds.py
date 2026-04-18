#!/usr/bin/env python3
import asyncio
import re
from urllib.parse import urljoin, urlparse
import httpx
from app.backend.services.news_api_service import _parse_rss_payload

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/115.0.0.0 Safari/537.36"
)

async def fetch_text(url: str):
    async with httpx.AsyncClient(headers={"User-Agent": USER_AGENT}, timeout=15.0, follow_redirects=True) as client:
        try:
            r = await client.get(url)
            r.raise_for_status()
            return r.text, r.url
        except Exception as e:
            print(f"Failed to fetch {url}: {e}")
            return None, None


def find_feed_links(html: str, base: str) -> list[str]:
    found = []
    # look for link rel alternate RSS/Atom
    for m in re.finditer(r'<link[^>]+rel=["\']?alternate["\']?[^>]*>', html, flags=re.I):
        tag = m.group(0)
        type_m = re.search(r'type=["\']([^"\']+)["\']', tag, flags=re.I)
        href_m = re.search(r'href=["\']([^"\']+)["\']', tag, flags=re.I)
        if not href_m:
            continue
        href = href_m.group(1)
        if type_m:
            t = type_m.group(1).lower()
            if 'rss' in t or 'atom' in t or 'xml' in t:
                found.append(urljoin(base, href))
                continue
        # accept if href contains 'rss' or 'feed'
        if 'rss' in href.lower() or 'feed' in href.lower():
            found.append(urljoin(base, href))

    # also search for <a> with rss text
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', html, flags=re.I|re.S):
        href, inner = m.group(1), m.group(2)
        if 'rss' in inner.lower() or 'feed' in inner.lower() or 'подпис' in inner.lower():
            found.append(urljoin(base, href))
    # unique preserve order
    out = []
    for u in found:
        if u not in out:
            out.append(u)
    return out


async def try_feed(url: str, name: str):
    text, final_url = await fetch_text(url)
    if not text:
        return []
    # quick check for rss/atom
    if '<item' in text.lower() or '<entry' in text.lower() or 'application/rss+xml' in text.lower():
        items = _parse_rss_payload(text, name, 100)
        return items
    # if it's html, try to discover
    links = find_feed_links(text, final_url or url)
    results = []
    for link in links:
        print(f" Discovered candidate: {link}")
        t, _ = await fetch_text(link)
        if not t:
            continue
        if '<item' in t.lower() or '<entry' in t.lower():
            items = _parse_rss_payload(t, name, 100)
            results.extend(items)
    return results


async def main():
    sites = [
        ("Gazeta.uz", "https://www.gazeta.uz/ru/"),
        ("Daryo", "https://daryo.uz/"),
    ]
    for name, base in sites:
        print(f"\nChecking site {name}: {base}")
        items = await try_feed(base, name)
        print(f"Found {len(items)} feed items for {name}")
        for i, it in enumerate(items[:8], 1):
            print(f" {i}. {it.get('title')[:140]} — {it.get('url')} — {it.get('publishedAt')}")

if __name__ == '__main__':
    asyncio.run(main())
