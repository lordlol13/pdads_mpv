from __future__ import annotations
from typing import Optional
from bs4 import BeautifulSoup
from urllib.parse import urlparse, quote
import httpx
import json


def _join_paragraphs(el) -> str:
    # prefer explicit paragraph tags
    ps = [p.get_text(" ", strip=True) for p in el.find_all("p")]
    txt = "\n".join([p for p in ps if p])
    if txt and len(txt) > 20:
        return txt

    # fallback: collect text from obvious block children
    blocks = []
    for child in el.find_all(recursive=False):
        if child.name in ("div", "section", "article", "p"):
            t = child.get_text(" ", strip=True)
            if t:
                blocks.append(t)
    if blocks:
        txt2 = "\n".join(blocks)
        if len(txt2) > 20:
            return txt2

    # final fallback: whole element text
    return el.get_text(" ", strip=True)


def extract_daryo(soup: BeautifulSoup, url: Optional[str] = None) -> str:
    # API-first: try site API (clean source) when URL is available
    try:
        if url:
            api_txt = _fetch_daryo_api_text(url)
            if api_txt and len(api_txt) > 200:
                return api_txt
    except Exception:
        pass
    selectors = [
        ".news-section-main-content",
        ".section-pages__wrapper_content",
        ".layout-body",
        "div.article-body",
        "div.article_text",
        ".article-body",
        ".post-content",
        ".entry-content",
        "[itemprop=articleBody]",
        ".content",
        ".article-text",
        ".news-text",
        "article",
    ]

    def _is_ui_text(t: str) -> bool:
        if not t:
            return True
        s = t.strip()
        if len(s) < 40:
            return True
        low = s.lower()
        bad = [
            "izoh qoldirish",
            "ro‘yxatdan",
            "xato topdingizmi",
            "cookies",
            "guvohnoma",
            "0944-sonli",
            "elektron manzil",
            "o'zmaa",
            "o‘zmaa",
            "axborot va ommaviy kommunikatsiyalar agentligi",
            "©",
            "muallif",
        ]
        for b in bad:
            if b in low:
                return True
        return False

    remove_selectors = [
        ".post-footer",
        ".footer",
        ".share",
        ".article__meta",
        ".post-meta",
        ".author",
        ".article-author",
        ".tags",
        ".related",
        ".newsletter",
        ".cookie",
        ".site-info",
        ".note",
        ".advertisement",
        ".ads",
        ".post__tags",
        ".post-info",
        ".advert",
    ]

    attr_markers = ["0944-sonli", "guvohnoma", "o'zmaa", "o‘zmaa", "axborot va ommaviy kommunikatsiyalar agentligi"]

    for sel in selectors:
        el = soup.select_one(sel)
        if not el:
            continue

        # remove obvious noise blocks inside the container
        try:
            for rs in remove_selectors:
                for node in el.select(rs):
                    node.decompose()
        except Exception:
            pass

        # remove nodes that contain attribution/legal markers
        try:
            for node in list(el.find_all(recursive=True)):
                try:
                    txt = node.get_text(" ", strip=True).lower()
                except Exception:
                    txt = ""
                if not txt:
                    continue
                for m in attr_markers:
                    if m in txt:
                        try:
                            node.decompose()
                        except Exception:
                            pass
                        break
        except Exception:
            pass

        # collect paragraphs and filter UI-like paragraphs
        try:
            ps = [p.get_text(" ", strip=True) for p in el.find_all("p")]
            good = [p for p in ps if p and not _is_ui_text(p)]
            if good:
                joined = "\n".join(good)
                if len(joined) > 120:
                    return joined
        except Exception:
            pass

        # fallback to existing joiner but after cleaning
        try:
            txt = _join_paragraphs(el)
            if txt and len(txt) > 120 and not any(m in txt.lower() for m in attr_markers):
                return txt
        except Exception:
            pass

    return generic_extract(soup)


def _find_text_in_json(obj) -> Optional[str]:
    candidates = []

    def walk(o):
        if isinstance(o, str):
            candidates.append(o)
        elif isinstance(o, dict):
            for k, v in o.items():
                if isinstance(v, (dict, list)):
                    walk(v)
                elif isinstance(v, str) and len(v) > 30:
                    candidates.append(v)
        elif isinstance(o, list):
            for it in o[:50]:
                walk(it)

    try:
        walk(obj)
    except Exception:
        return None

    if not candidates:
        return None
    candidates = [c.strip() for c in candidates if c and isinstance(c, str)]
    candidates.sort(key=lambda s: len(s), reverse=True)
    return candidates[0]


def _fetch_daryo_api_text(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        path = parsed.path or ''
        # slug is last path segment
        slug = ''
        parts = [p for p in path.split('/') if p]
        if parts:
            slug = parts[-1]
        if not slug:
            return None

        # detect locale from path prefix (e.g. /ru/2026/...)
        lang = 'oz'
        if len(parts) >= 1 and parts[0] in ('ru', 'oz', 'uz', 'en'):
            lang = parts[0]

        api_url = f"https://data.daryo.uz/api/v1/site/news/{quote(slug)}"
        headers = {"Accept-Language": lang}
        r = httpx.get(api_url, headers=headers, timeout=10.0)
        if r.status_code != 200:
            return None
        try:
            j = r.json()
        except Exception:
            # sometimes API returns plain text
            txt = r.text or None
            return txt

        # API often returns object with .data
        if isinstance(j, dict) and 'data' in j and j['data']:
            j2 = j['data']
        else:
            j2 = j

        best = _find_text_in_json(j2)
        if best:
            # if it's HTML, strip tags
            if '<p' in best or '<div' in best or '<br' in best:
                try:
                    bs = BeautifulSoup(best, 'lxml')
                    return _join_paragraphs(bs)
                except Exception:
                    return best
            return best
    except Exception:
        return None
    return None


def extract_gazeta(soup: BeautifulSoup) -> str:
    selectors = [
        ".article__body",
        ".post__text",
        ".article-body",
        ".content",
        ".post-content",
        ".entry-content",
        "[itemprop=articleBody]",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = _join_paragraphs(el)
            if len(txt) > 120:
                return txt
    return generic_extract(soup)


def extract_kun(soup: BeautifulSoup) -> str:
    selectors = [
        ".news-text",
        ".article__text",
        ".article-text",
        ".content",
        ".news-content",
        ".article-body",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = _join_paragraphs(el)
            if len(txt) > 120:
                return txt
    return generic_extract(soup)


def extract_podrobno(soup: BeautifulSoup) -> str:
    selectors = [".article-text", ".article-body", ".content", ".text"]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = _join_paragraphs(el)
            if len(txt) > 120:
                return txt
    return generic_extract(soup)


def extract_uznews(soup: BeautifulSoup) -> str:
    selectors = [".post", ".article", ".article-body", ".entry-content", ".content"]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = _join_paragraphs(el)
            if len(txt) > 120:
                return txt
    return generic_extract(soup)


def extract_uz24(soup: BeautifulSoup) -> str:
    selectors = [".item-body", ".post-content", ".article-body", ".content"]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = _join_paragraphs(el)
            if len(txt) > 120:
                return txt
    return generic_extract(soup)


def generic_extract(soup: BeautifulSoup) -> str:
    selectors = [
        ".post-content",
        ".article-body",
        ".entry-content",
        "[itemprop=articleBody]",
        ".content",
        ".article-text",
        ".news-text",
        ".article__body",
        ".post__text",
    ]
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            txt = _join_paragraphs(el)
            if len(txt) > 120:
                return txt
    # fallback: top-level paragraphs
    ps = [p.get_text(" ", strip=True) for p in soup.find_all("p")]
    txt = "\n".join([p for p in ps if p])
    return txt


def extract_by_domain(url: Optional[str], soup: BeautifulSoup) -> str:
    if not url:
        return generic_extract(soup)
    host = urlparse(url).netloc.lower()
    if "daryo.uz" in host:
        return extract_daryo(soup, url)
    if "gazeta.uz" in host:
        return extract_gazeta(soup)
    if "kun.uz" in host:
        return extract_kun(soup)
    if "podrobno.uz" in host:
        return extract_podrobno(soup)
    if "uznews.uz" in host:
        return extract_uznews(soup)
    if "uz24.uz" in host:
        return extract_uz24(soup)
    return generic_extract(soup)


__all__ = [
    "extract_by_domain",
    "extract_daryo",
    "extract_gazeta",
    "extract_kun",
    "extract_podrobno",
    "extract_uznews",
    "extract_uz24",
    "generic_extract",
]
