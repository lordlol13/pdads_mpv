from __future__ import annotations

import asyncio
from typing import Any

from app.backend.services.http_client import get_async_client

NEWS_API_URL = "https://newsapi.org/v2/everything"


async def fetch_newsapi(session, query: str, page_size: int = 12, api_key: str | None = None) -> list[dict[str, Any]]:
    if not api_key:
        return []

    params = {
        "q": query,
        "language": "en",
        "sortBy": "publishedAt",
        "pageSize": page_size,
        "apiKey": api_key,
    }

    resp = await session.get(NEWS_API_URL, params=params)
    try:
        resp.raise_for_status()
        payload = resp.json()
    except Exception:
        try:
            payload = await resp.json()
        except Exception:
            return []

    return payload.get("articles") or []


async def extract_article(session, url: str, max_paragraphs: int = 10, verbose: bool = False) -> str | None:
    try:
        resp = await session.get(url, timeout=10.0)
        resp.raise_for_status()
        html = await resp.text()
    except Exception:
        if verbose:
            print(f"[global_fetcher.extract_article] failed request: {url}")
        return None

    # lightweight extraction: try multiple heuristics
    try:
        from bs4 import BeautifulSoup
    except Exception:
        return None

    import re

    soup = BeautifulSoup(html, "html.parser")

    # 1) Common case: <p> paragraphs
    paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
    combined = "\n\n".join(paragraphs[:max_paragraphs]) if paragraphs else ""
    if combined and len(combined) >= 80:
        return combined

    # 2) Try <article> tag
    article_tag = soup.find("article")
    if article_tag:
        text = article_tag.get_text("\n\n", strip=True)
        if text and len(text) >= 80:
            return "\n\n".join(text.splitlines()[:max_paragraphs])

    # 3) Heuristic: look for large content-like blocks by class name
    candidates = []
    cls_re = re.compile(r"(article|content|post|entry|story|body|article-body|main|news)", re.I)
    for el in soup.find_all(attrs={"class": cls_re}):
        t = el.get_text("\n\n", strip=True)
        if t:
            candidates.append(t)
    if candidates:
        # choose the largest candidate
        best = max(candidates, key=lambda x: len(x))
        if len(best) >= 80:
            return "\n\n".join(best.splitlines()[:max_paragraphs])

    # 4) meta description fallback
    meta = soup.find("meta", attrs={"name": "description"}) or soup.find("meta", attrs={"property": "og:description"})
    if meta and meta.get("content"):
        desc = meta.get("content").strip()
        if desc:
            return desc

    if verbose:
        print(f"[global_fetcher.extract_article] no sufficient content for: {url}")

    return None


async def fetch_global_news(
    queries: list[str], page_size: int = 12, api_key: str | None = None, verbose: bool = False
) -> list[dict[str, Any]]:
    if not queries:
        return []

    if not api_key:
        if verbose:
            print("[global_fetcher] NEWS_API_KEY not set; skipping NewsAPI fetch")
        return []

    client = await get_async_client()
    tasks = [fetch_newsapi(client, q, page_size=page_size, api_key=api_key) for q in queries]
    batches = await asyncio.gather(*tasks)

    total_candidates = sum(len(b) for b in batches if b)
    if verbose:
        print(f"[global_fetcher] NewsAPI returned {total_candidates} candidate articles across {len(batches)} queries")

    articles: list[dict[str, Any]] = []
    extract_tasks = []
    for batch in batches:
        for art in batch:
            url = art.get("url")
            if not url:
                continue
            extract_tasks.append((art, extract_article(client, url, verbose=verbose)))

    if verbose:
        print(f"[global_fetcher] extracted {len(extract_tasks)} candidate URLs to fetch")

    # run extractors in limited concurrency
    sem = asyncio.Semaphore(8)

    async def _wrap(art, coro):
        async with sem:
            text = await coro
            return art, text

    wrapped = [_wrap(a, c) for a, c in extract_tasks]
    for fut in asyncio.as_completed(wrapped):
        art, text = await fut
        final_text = text
        if not final_text:
            # fallback to NewsAPI provided content/description if extraction failed
            final_text = art.get("content") or art.get("description") or ""
            if final_text and isinstance(final_text, str) and len(final_text) >= 80:
                if verbose:
                    print(f"[global_fetcher] using fallback content for {art.get('url')}")
            else:
                continue

        articles.append(
            {
                "title": art.get("title") or "",
                "content": final_text,
                "source_url": art.get("url"),
                "source_type": "global",
                "published_at": art.get("publishedAt"),
            }
        )

    if verbose:
        print(f"[global_fetcher] returning {len(articles)} extracted articles")

    return articles
