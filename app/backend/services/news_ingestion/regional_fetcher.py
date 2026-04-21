from __future__ import annotations

import asyncio
from typing import Any, Iterable, List, Optional
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
import re

from app.backend.services.http_client import get_async_client
from app.backend.services.news_ingestion.extractors import extract_daryo, extract_kun, is_good_image

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

DEFAULT_SOURCES = [
    "https://daryo.uz/uzbekiston/",
    "https://daryo.uz/category/uzbekiston/",
    "https://kun.uz/news",
    "https://kun.uz/news/list",
]

# module-level image dedupe for a single run
_seen_images: set[str] = set()


def _is_bad_image(url: str) -> bool:
    bad_keywords = ("logo", "icon", "ads", "banner", "placeholder", "avatar", "thumb", "small")
    low = (url or "").lower()
    return any(k in low for k in bad_keywords) or low.startswith("data:")


def fallback_image() -> str:
    # lightweight generic news image as fallback when no good image found
    return "https://source.unsplash.com/800x600/?news"


def is_daryo_article_url(full_url: str) -> bool:
    try:
        p = urlparse(full_url)
        path = (p.path or "").lower()
        if "daryo.uz" not in (p.netloc or ""):
            return False
        # dated paths like /2026/04/19/... are the most reliable
        if re.search(r"/20\d{2}", path):
            return True
        if "/article" in path or "/news" in path:
            return True
        if "-" in path and len(path) > 6:
            return True
        return False
    except Exception:
        return False


def is_kun_article_url(full_url: str) -> bool:
    try:
        p = urlparse(full_url)
        path = (p.path or "").lower()
        if "kun.uz" not in (p.netloc or ""):
            return False
        # prefer /news/<slug> with hyphen or dated paths
        if path.startswith("/news/") and (re.search(r"/20\d{2}", path) or ("-" in path)):
            return True
        # fallback: dated /20xx in path
        if re.search(r"/20\d{2}", path) and "/news" in path:
            return True
        return False
    except Exception:
        return False


class RegionalFetcher:
    def __init__(self, concurrency: int = 8, timeout: float = 10.0, min_image_size: int = 10_000, verbose: bool = False):
        self._sem = asyncio.Semaphore(concurrency)
        self.timeout = timeout
        self.min_image_size = min_image_size
        self.verbose = verbose

    async def fetch(self, sources: Optional[Iterable[str]] = None, per_source_limit: int = 8) -> List[dict[str, Any]]:
        sources = list(sources or DEFAULT_SOURCES)
        client = await get_async_client()

        tasks = [self._fetch_source(client, s, per_source_limit) for s in sources]
        parts = await asyncio.gather(*tasks)
        articles: list[dict[str, Any]] = []
        for part in parts:
            if part:
                articles.extend(part)
        return articles

    async def _fetch_source(self, client: httpx.AsyncClient, base_url: str, per_source_limit: int) -> List[dict[str, Any]]:
        html = await self._get_html(client, base_url)
        if not html:
            if self.verbose:
                print(f"[regional_fetcher] empty html for {base_url}")
            return []

        soup = BeautifulSoup(html, "html.parser")

        candidates: list[str] = []
        seen: set[str] = set()
        raw_links: list[str] = []
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            if not href:
                continue
            if href.startswith("//"):
                href = "https:" + href
            raw_links.append(href)

        if self.verbose:
            print(f"[regional_fetcher] Found {len(raw_links)} raw links for {base_url}")
            print(f"[regional_fetcher] Sample raw links: {raw_links[:10]}")

        for href in raw_links:
            full = urljoin(base_url, href)
            p = urlparse(full)
            if not p.scheme.startswith("http"):
                continue

            # strict per-site filters
            is_article = False
            if "daryo.uz" in base_url or "daryo.uz" in p.netloc:
                is_article = is_daryo_article_url(full)
            elif "kun.uz" in base_url or "kun.uz" in p.netloc:
                is_article = is_kun_article_url(full)
            else:
                path = (p.path or "").lower()
                is_article = "/20" in path or "/news" in path or ("-" in path and len(path) > 4)

            if is_article:
                norm = full.split("#")[0]
                if norm not in seen:
                    seen.add(norm)
                    candidates.append(norm)
            else:
                if self.verbose and len(candidates) < 5:
                    print(f"[regional_fetcher] skipped candidate: {full}")

            if len(candidates) >= per_source_limit:
                break

        if self.verbose:
            print(f"[regional_fetcher] {base_url}: found {len(candidates)} candidate links")

        # process links with concurrency limit
        tasks = [self._process_link(client, u, base_url) for u in candidates]
        results = await asyncio.gather(*tasks)

        # dedupe by image URL and URL
        out: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for r in results:
            if not r:
                continue
            u = (r.get("source_url") or "").split("#")[0]
            if not u or u in seen_urls:
                continue
            img = r.get("image_url")
            if not img:
                continue
            # allow fallback image to appear multiple times (don't dedupe by fallback)
            if img in _seen_images and img != fallback_image():
                if self.verbose:
                    print(f"[regional_fetcher] duplicate image skipped: {img}")
                continue
            seen_urls.add(u)
            _seen_images.add(img)
            out.append(r)

        return out

    async def _process_link(self, client: httpx.AsyncClient, url: str, base_url: str) -> Optional[dict[str, Any]]:
        async with self._sem:
            return await self._extract_article(client, url, base_url)

    async def _extract_article(self, client: httpx.AsyncClient, url: str, base_url: str) -> Optional[dict[str, Any]]:
        try:
            html = await self._get_html(client, url)
            if not html:
                return None
            soup = BeautifulSoup(html, "html.parser")

            # Site-specific extractors for higher-quality extraction
            site_data = None
            if "daryo.uz" in url or "daryo.uz" in base_url:
                try:
                    site_data = extract_daryo(html, base_url)
                except Exception as e:  # pragma: no cover - tolerate extractor errors
                    if self.verbose:
                        print(f"[regional_fetcher] daryo extractor failed for {url}: {e}")
            elif "kun.uz" in url or "kun.uz" in base_url:
                try:
                    site_data = extract_kun(html, base_url)
                except Exception as e:  # pragma: no cover - tolerate extractor errors
                    if self.verbose:
                        print(f"[regional_fetcher] kun extractor failed for {url}: {e}")

            if site_data:
                title = site_data.get("title") or ""
                text = site_data.get("content") or ""
                # enforce minimal length for quality
                if not text or len(text) < 80:
                    if self.verbose:
                        print(f"[regional_fetcher] too short content for {url}: {len(text)} chars (site-specific)")
                    return None

                img_candidate = site_data.get("image_url")
                image = None
                if img_candidate and not _is_bad_image(img_candidate) and is_good_image(img_candidate):
                    full_img = urljoin(url, img_candidate)
                    try:
                        if await self._check_image_quality(client, full_img):
                            image = full_img
                    except Exception:
                        image = None

                if not image:
                    image = await self._extract_best_image(client, soup, base_url) or fallback_image()

                return {
                    "title": title or "",
                    "content": text,
                    "source_url": url,
                    "image_url": image,
                    "source_type": "regional",
                }

            # Fallback generic extraction when no site-specific handler
            # title
            title_tag = soup.find("h1")
            title = title_tag.get_text(strip=True) if title_tag and title_tag.get_text() else ""
            if not title:
                # fallback to meta
                meta_title = soup.find("meta", property="og:title") or soup.find("meta", attrs={"name": "title"})
                if meta_title and meta_title.get("content"):
                    title = meta_title.get("content").strip()

            # text
            paragraphs = [p.get_text(strip=True) for p in soup.find_all("p")]
            text = "\n\n".join([p for p in paragraphs if p])

            # soft filter for content length (relaxed for better recall)
            if not text or len(text) < 80:
                if self.verbose:
                    print(f"[regional_fetcher] too short content for {url}: {len(text)} chars")
                return None

            # image (allow fallback when no good image found)
            image = await self._extract_best_image(client, soup, base_url)
            if not image:
                if self.verbose:
                    print(f"[regional_fetcher] no good image for {url}; using fallback")
                image = fallback_image()

            return {
                "title": title or "",
                "content": text,
                "source_url": url,
                "image_url": image,
                "source_type": "regional",
            }
        except Exception as exc:  # pragma: no cover - tolerate site errors
            if self.verbose:
                print(f"[regional_fetcher] error extracting {url}: {exc}")
            return None

    async def _get_html(self, client: httpx.AsyncClient, url: str) -> str:
        try:
            resp = await client.get(url, headers=HEADERS, timeout=self.timeout)
            status = resp.status_code
            try:
                raw = await resp.aread()
                if raw:
                    try:
                        body = raw.decode(resp.encoding or "utf-8", errors="replace")
                    except Exception:
                        body = raw.decode("utf-8", errors="replace")
                else:
                    body = ""
            except Exception:
                body = ""
            if self.verbose:
                print(f"[regional_fetcher._get_html] {url} -> status={status}, len={len(body)}")
                # key headers for diagnosis
                hdrs = {k: v for k, v in resp.headers.items() if k.lower() in ('content-type', 'content-length', 'server', 'content-encoding')}
                print(f"[regional_fetcher._get_html] headers: {hdrs}")
                if body:
                    print(body[:200].replace('\n', ' '))
            resp.raise_for_status()
            return body
        except Exception:
            if self.verbose:
                print(f"[regional_fetcher] failed GET {url}")
            return ""

    async def _extract_best_image(self, client: httpx.AsyncClient, soup: BeautifulSoup, base_url: str) -> Optional[str]:
        candidates: list[str] = []

        # 1) og:image
        og = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
        if og and og.get("content"):
            candidates.append(urljoin(base_url, og.get("content")))

        # 2) twitter:image
        tw = soup.find("meta", property="twitter:image") or soup.find("meta", attrs={"name": "twitter:image"})
        if tw and tw.get("content"):
            candidates.append(urljoin(base_url, tw.get("content")))

        # 3) images in content
        for img in soup.find_all("img"):
            src = img.get("src") or img.get("data-src") or img.get("data-original")
            if not src:
                continue
            src = src.strip()
            full = urljoin(base_url, src)
            if _is_bad_image(full):
                continue
            candidates.append(full)

        # preserve order and dedupe
        seen_local: set[str] = set()
        unique: list[str] = []
        for c in candidates:
            if c not in seen_local:
                seen_local.add(c)
                unique.append(c)

        # quality check
        for c in unique:
            if await self._check_image_quality(client, c):
                return c
        return None

    async def _check_image_quality(self, client: httpx.AsyncClient, url: str) -> bool:
        try:
            # prefer HEAD to get size quickly
            resp = await client.head(url, headers=HEADERS, timeout=self.timeout, follow_redirects=True)
            ct = (resp.headers.get("content-type") or "").lower()
            if "image" not in ct:
                return False
            size = int(resp.headers.get("content-length") or 0)
            if size and size >= self.min_image_size:
                return True

            # fallback: try GET and read limited bytes
            r = await client.get(url, headers=HEADERS, timeout=self.timeout)
            r.raise_for_status()
            b = await r.aread()
            if len(b) >= self.min_image_size and ("image" in (r.headers.get("content-type") or "").lower()):
                return True
            return False
        except Exception:
            if self.verbose:
                print(f"[regional_fetcher] image quality check failed for {url}")
            return False


async def fetch_regional_news(sources: Optional[Iterable[str]] = None, per_source_limit: int = 8, verbose: bool = False) -> List[dict[str, Any]]:
    fetcher = RegionalFetcher(verbose=verbose)
    return await fetcher.fetch(sources=sources or DEFAULT_SOURCES, per_source_limit=per_source_limit)
