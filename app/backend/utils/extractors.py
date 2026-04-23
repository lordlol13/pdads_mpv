"""Production-ready article extractor utilities.

Provides synchronous and async helpers to extract title, content
and a high-quality image (prefer og:image, fallback to best <img>). 
Designed to be safe for inclusion in async pipelines.

Usage:
  from app.backend.utils.extractors import extract_article_async, extract_article

"""
from __future__ import annotations

import re
import asyncio
from typing import Optional
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
import os
import logging
import httpx

LOG = logging.getLogger(__name__)

# Optional: perform HEAD requests to verify image size/content-type when enabled.
HEAD_CHECK_ENABLED = str(os.getenv("EXTRACTOR_CHECK_IMAGE_HEAD") or "").lower() in ("1", "true", "yes")
HEAD_CHECK_MIN_BYTES = int(os.getenv("EXTRACTOR_CHECK_IMAGE_MIN_BYTES") or 20000)


def _is_site_host(url: str, host_substr: str) -> bool:
    try:
        return host_substr in urlparse(url).netloc.lower()
    except Exception:
        return host_substr in (url or "")


BAD_IMAGE_KEYWORDS = [
    "logo",
    "banner",
    "ads",
    "adserver",
    "icon",
    "avatar",
    "sprite",
    "thumb",
    "thumbnail",
    "placeholder",
]

IMAGE_EXTENSIONS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif")


def _is_data_uri(url: str) -> bool:
    return url.startswith("data:")


def is_good_image(url: Optional[str]) -> bool:
    if not url:
        return False
    url_l = url.lower()
    if _is_data_uri(url_l):
        return False
    if any(bad in url_l for bad in BAD_IMAGE_KEYWORDS):
        return False
    parsed = urlparse(url_l)
    path = parsed.path or ""
    if any(path.endswith(ext) for ext in IMAGE_EXTENSIONS):
        return True
    # heuristic: if path contains "images" or "img" and no obvious bad token
    if "images" in path or "img" in path:
        return True
    return False


def extract_og_image(soup: BeautifulSoup, base_url: str = "") -> Optional[str]:
    # preferred tags
    tag = soup.find("meta", property="og:image")
    if tag and tag.get("content"):
        return urljoin(base_url, tag["content"].strip())
    tag = soup.find("meta", attrs={"name": "twitter:image"})
    if tag and tag.get("content"):
        return urljoin(base_url, tag["content"].strip())
    tag = soup.find("link", rel="image_src")
    if tag and tag.get("href"):
        return urljoin(base_url, tag["href"].strip())
    return None


def _parse_srcset_choose_largest(srcset: str, base_url: str = "") -> Optional[str]:
    if not srcset:
        return None
    candidates = []
    for part in srcset.split(","):
        part = part.strip()
        if not part:
            continue
        # formats: "url 400w" or "url 2x" or just "url"
        m = re.match(r"^(\S+)(?:\s+(\d+)[wWx])?$", part)
        if m:
            url = m.group(1)
            size = int(m.group(2)) if m.group(2) else 0
            candidates.append((size, urljoin(base_url, url)))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    return candidates[0][1]


def extract_first_large_image(soup: BeautifulSoup, base_url: str) -> Optional[str]:
    # collect candidates preserving order
    seen: set[str] = set()
    candidates: list[str] = []

    # prefer srcset (largest candidate)
    for img in soup.find_all("img"):
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            candidate = _parse_srcset_choose_largest(srcset, base_url)
            if candidate:
                norm = normalize_image(candidate)
                if norm and norm not in seen and is_good_image(norm):
                    seen.add(norm)
                    candidates.append(norm)

    # images with explicit src/data-src/data-lazy-src attributes
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not src:
            continue
        full_url = urljoin(base_url, src)
        norm = normalize_image(full_url)
        if not norm or norm in seen:
            continue

        # prefer images that do not look like thumbs/icons
        low = norm.lower()
        if any(x in low for x in ("thumb", "thumbnail", "small", "icon", "sprite")):
            continue

        # prefer images with width/height attributes when available
        width = img.get("width") or img.get("data-width")
        height = img.get("height") or img.get("data-height")
        try:
            if width and str(width).isdigit() and int(width) < 240:
                continue
        except Exception:
            pass

        if is_good_image(norm):
            seen.add(norm)
            candidates.append(norm)

    # final fallback: any image found earlier and passes is_good_image
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src")
        if not src:
            continue
        full_url = urljoin(base_url, src)
        norm = normalize_image(full_url)
        if not norm or norm in seen:
            continue
        if is_good_image(norm):
            # optionally verify remote size to avoid tiny icons
            if HEAD_CHECK_ENABLED:
                try:
                    if not _check_image_head(norm, min_bytes=HEAD_CHECK_MIN_BYTES):
                        continue
                except Exception:
                    # do not fail the extractor because head check failed
                    pass
            seen.add(norm)
            candidates.append(norm)

    # return first candidate if any
    return candidates[0] if candidates else None


def _check_image_head(url: str, min_bytes: int = 20000, timeout: float = 5.0) -> bool:
    try:
        # Use a lightweight HEAD request
        resp = httpx.head(url, timeout=timeout, follow_redirects=True)
        if resp.status_code != 200:
            return False
        ctype = (resp.headers.get("content-type") or "").lower()
        if not ctype.startswith("image/"):
            return False
        clen = resp.headers.get("content-length")
        if clen:
            try:
                if int(clen) < int(min_bytes):
                    return False
            except Exception:
                pass
        return True
    except Exception:
        return False


def extract_title(soup: BeautifulSoup) -> Optional[str]:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og.get("content").strip()
    if soup.title and soup.title.string:
        return soup.title.string.strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    return None


def extract_content(soup: BeautifulSoup) -> str:
    paragraphs = soup.find_all("p")
    text = []
    for p in paragraphs:
        t = p.get_text(separator=" ", strip=True)
        if len(t) > 50:
            text.append(t)
    return "\n\n".join(text).strip()


def normalize_image(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    try:
        # strip query string and fragment — often safe and yields canonical URL
        return url.split("?")[0].split("#")[0]
    except Exception:
        return url


def extract_article(html: str, url: str) -> dict:
    """Extract article fields from HTML.

    Returns: { title, content, image_url, source_url }
    """
    soup = BeautifulSoup(html, "html.parser")

    # Router: prefer site-specific extractors for better accuracy
    try:
        if _is_site_host(url, "daryo.uz"):
            return _extract_daryo(html, url)
        if _is_site_host(url, "kun.uz"):
            return _extract_kun(html, url)
    except Exception:
        LOG.exception("site-specific extractor failed for %s", url)

    # Generic fallback
    image = extract_og_image(soup, url)
    if not image:
        image = extract_first_large_image(soup, url)
    image = normalize_image(image)

    title = extract_title(soup)
    content = extract_content(soup)

    return {
        "title": title,
        "content": content,
        "image_url": image,
        "source_url": url,
    }


def _extract_daryo(html: str, url: str) -> dict:
    """Site-specific extractor for daryo.uz"""
    soup = BeautifulSoup(html, "html.parser")
    # title
    title_el = soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else extract_title(soup)

    # main content
    content_el = None
    for sel in (".news-section-main-content", ".post-content", ".article-body", ".entry-content", "article"):
        content_el = soup.select_one(sel)
        if content_el:
            break
    content = ""
    if content_el:
        paragraphs = [p.get_text(" ", strip=True) for p in content_el.find_all("p")]
        content = "\n\n".join([p for p in paragraphs if p and len(p) > 40])
    if not content:
        content = extract_content(soup)

    # image: prefer og, then specific selectors, then generic
    image = extract_og_image(soup, url)
    if not image:
        # daryo often has figure img inside .article-body
        img = soup.select_one(".article-body img, .post-content img, figure img")
        if img and (img.get("src") or img.get("data-src") or img.get("srcset")):
            src = img.get("src") or img.get("data-src")
            image = urljoin(url, src)
    if not image:
        image = extract_first_large_image(soup, url)
    image = normalize_image(image)

    return {"title": title, "content": content, "image_url": image, "source_url": url}


def _extract_kun(html: str, url: str) -> dict:
    """Site-specific extractor for kun.uz"""
    soup = BeautifulSoup(html, "html.parser")
    title_el = soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else extract_title(soup)

    content_el = None
    for sel in (".news-text", ".article__text", ".article-text", ".content", "article"):
        content_el = soup.select_one(sel)
        if content_el:
            break
    content = ""
    if content_el:
        paragraphs = [p.get_text(" ", strip=True) for p in content_el.find_all("p")]
        content = "\n\n".join([p for p in paragraphs if p and len(p) > 40])
    if not content:
        content = extract_content(soup)

    image = extract_og_image(soup, url)
    if not image:
        img = soup.select_one(".news-text img, .article__text img, figure img")
        if img and (img.get("src") or img.get("data-src") or img.get("srcset")):
            src = img.get("src") or img.get("data-src")
            image = urljoin(url, src)
    if not image:
        image = extract_first_large_image(soup, url)
    image = normalize_image(image)

    return {"title": title, "content": content, "image_url": image, "source_url": url}


async def extract_article_async(html: str, url: str) -> dict:
    """Async wrapper for use in async pipelines."""
    return await asyncio.to_thread(extract_article, html, url)


__all__ = [
    "extract_article",
    "extract_article_async",
    "normalize_image",
    "is_good_image",
]
