from __future__ import annotations

from typing import Dict, Optional, List
from urllib.parse import urlparse

from bs4 import BeautifulSoup


def _text_from_element(el) -> str:
    if not el:
        return ""
    paragraphs = el.find_all("p")
    if paragraphs:
        return "\n\n".join(p.get_text(strip=True) for p in paragraphs if p.get_text(strip=True))
    # fallback to element text
    return (el.get_text(separator="\n\n", strip=True) or "").strip()


def _largest_text_block(soup: BeautifulSoup) -> str:
    candidates = []
    for tag in soup.find_all(["article", "main", "section", "div"]):
        text = _text_from_element(tag)
        if text:
            candidates.append(text)

    # fallback to body paragraphs grouping
    if not candidates:
        body = soup.body or soup
        paragraphs = body.find_all("p")
        if paragraphs:
            groups = []
            current = []
            last_parent = None
            for p in paragraphs:
                parent = p.parent
                if last_parent is None or parent is last_parent:
                    current.append(p)
                else:
                    groups.append(current)
                    current = [p]
                last_parent = parent
            if current:
                groups.append(current)
            for g in groups:
                text = "\n\n".join(p.get_text(strip=True) for p in g if p.get_text(strip=True))
                if text:
                    candidates.append(text)

    if not candidates:
        return ""
    return max(candidates, key=lambda t: len(t))


def _find_first_text(soup: BeautifulSoup, selectors: List[str]) -> Optional[str]:
    for sel in selectors:
        try:
            el = soup.select_one(sel)
        except Exception:
            el = None
        if not el:
            continue
        text = _text_from_element(el)
        if text:
            return text
    return None


def _find_first_title(soup: BeautifulSoup, selectors: List[str]) -> Optional[str]:
    for sel in selectors:
        try:
            el = soup.select_one(sel)
        except Exception:
            el = None
        if not el:
            continue
        if el.name == "meta":
            content = el.get("content")
            if content:
                return content.strip()
        else:
            val = el.get_text(strip=True)
            if val:
                return val
    return None


def parse_article_by_domain(html: str | None, url: str | None) -> Dict[str, Optional[str]]:
    """Try site-specific selectors to extract title, body text, and og:image.

    Returns dict with keys: `title`, `raw_text`, `og_image` (any may be None).
    """
    result: Dict[str, Optional[str]] = {"title": None, "raw_text": None, "og_image": None}
    if not html:
        return result
    soup = BeautifulSoup(html, "html.parser")

    domain = ""
    try:
        domain = (urlparse(str(url or "")).netloc or "").lower().removeprefix("www.")
    except Exception:
        domain = ""

    # common og:image
    og = soup.select_one('meta[property="og:image"]') or soup.select_one('meta[name="twitter:image"]')
    if og and og.get("content"):
        result["og_image"] = og.get("content").strip()

    # site-specific heuristics
    if "gazeta.uz" in domain:
        title_sel = [
            'meta[property="og:title"]',
            "h1.article__title",
            "h1",
            "title",
        ]
        body_sel = [
            'div[itemprop="articleBody"]',
            ".article__content",
            ".article-content",
            ".post-content",
            ".entry-content",
        ]
        result["title"] = _find_first_title(soup, title_sel) or None
        result["raw_text"] = _find_first_text(soup, body_sel) or None
        if result["raw_text"] is None:
            result["raw_text"] = _largest_text_block(soup) or None
        return result

    if "daryo.uz" in domain:
        title_sel = [
            'meta[property="og:title"]',
            "h1.post__title",
            "h1",
            "title",
        ]
        body_sel = [
            ".post-text",
            ".article__body",
            ".entry-content",
            "div[itemprop=articleBody]",
        ]
        result["title"] = _find_first_title(soup, title_sel) or None
        result["raw_text"] = _find_first_text(soup, body_sel) or None
        if result["raw_text"] is None:
            result["raw_text"] = _largest_text_block(soup) or None
        return result

    if "kun.uz" in domain:
        title_sel = [
            'meta[property="og:title"]',
            "h1.article-title",
            "h1",
            "title",
        ]
        body_sel = [
            ".article-text",
            ".content",
            ".entry-content",
        ]
        result["title"] = _find_first_title(soup, title_sel) or None
        result["raw_text"] = _find_first_text(soup, body_sel) or None
        if result["raw_text"] is None:
            result["raw_text"] = _largest_text_block(soup) or None
        return result

    # Generic fallback for other domains
    title_sel = [
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
        "h1",
        "title",
    ]
    result["title"] = _find_first_title(soup, title_sel) or None
    result["raw_text"] = _largest_text_block(soup) or None
    return result
