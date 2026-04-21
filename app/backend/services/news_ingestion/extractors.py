from __future__ import annotations

from typing import Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import json
import re


def is_good_image(url: Optional[str]) -> bool:
    if not url:
        return False
    low = url.lower()
    bad = ("logo", "icon", "banner", "ads", "placeholder", "avatar", "thumb", "small")
    if low.startswith("data:"):
        return False
    return not any(b in low for b in bad)


def _meta_image(soup: BeautifulSoup) -> Optional[str]:
    m = soup.find("meta", property="og:image") or soup.find("meta", attrs={"name": "og:image"})
    if m and m.get("content"):
        return m.get("content").strip()
    t = soup.find("meta", property="twitter:image") or soup.find("meta", attrs={"name": "twitter:image"})
    if t and t.get("content"):
        return t.get("content").strip()
    return None


def extract_image(soup: BeautifulSoup, base_url: Optional[str] = None, min_src_len: int = 50) -> Optional[str]:
    """Fallback image extraction chain: og -> twitter -> first big <img>."""
    img = _meta_image(soup)
    if img:
        return urljoin(base_url, img) if base_url else img

    # twitter image already checked in _meta_image, keep redundancy safe
    t = soup.find("meta", property="twitter:image") or soup.find("meta", attrs={"name": "twitter:image"})
    if t and t.get("content"):
        tw = t.get("content").strip()
        return urljoin(base_url, tw) if base_url else tw

    # pick first reasonably long src (covers lazy-loaded images too)
    for img_tag in soup.find_all("img"):
        src = img_tag.get("src") or img_tag.get("data-src") or img_tag.get("data-original") or img_tag.get("srcset")
        if not src:
            continue
        src = src.strip()
        if len(src) >= min_src_len and is_good_image(src):
            return urljoin(base_url, src) if base_url else src

    return None



def _paragraphs_text(container: Optional[BeautifulSoup], min_len: int = 40) -> str:
    if not container:
        return ""
    ps = container.find_all("p")
    out: list[str] = []
    for p in ps:
        t = p.get_text(strip=True)
        if len(t) >= min_len:
            out.append(t)
    return "\n\n".join(out)


def extract_daryo(html: str, base_url: Optional[str] = None) -> dict:
    """Extract article fields from daryo.uz pages.

    Returns dict with keys: title, content, image_url
    """
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # common article container
    content_div = (
        soup.find("div", class_="post-content")
        or soup.find("div", id="article-body")
        or soup.find("article")
    )
    text = _paragraphs_text(content_div, min_len=40)

    # Some Daryo pages embed the article HTML inside a JS/JSON blob (escaped),
    # try to recover it when normal selectors fail.
    if not text:
        # 1) try JSON-LD articleBody
        try:
            import json

            for s in soup.find_all("script", type="application/ld+json"):
                try:
                    jd = json.loads(s.string or s.text)
                except Exception:
                    continue
                if isinstance(jd, dict) and jd.get("articleBody"):
                    ab = jd.get("articleBody") or ""
                    if ab:
                        asoup = BeautifulSoup(ab, "lxml")
                        text = _paragraphs_text(asoup, min_len=40)
                        if text:
                            break
                # sometimes it's a list
                if isinstance(jd, list):
                    for item in jd:
                        if isinstance(item, dict) and item.get("articleBody"):
                            ab = item.get("articleBody") or ""
                            asoup = BeautifulSoup(ab, "lxml")
                            text = _paragraphs_text(asoup, min_len=40)
                            if text:
                                break
                    if text:
                        break
        except Exception:
            pass

    if not text:
        import re

        for s in soup.find_all("script"):
            src = s.string or s.text or ""
            if not src:
                continue
            if "\\u003Cp" in src or "post-content-p" in src or "post-content" in src:
                # try to extract escaped fragment then decode unicode escapes
                m = re.search(r"(\\u003Cp.*?\\u003C\\/p\\u003E)", src, flags=re.DOTALL)
                frag = None
                if m:
                    frag = m.group(1)
                else:
                    # fallback: attempt to find a larger chunk around 'post-content'
                    idx = src.find("post-content")
                    if idx != -1:
                        start = max(0, idx - 200)
                        frag = src[start: start + 2000]

                if frag:
                    try:
                        decoded = bytes(frag, "utf-8").decode("unicode_escape")
                        asoup = BeautifulSoup(decoded, "lxml")
                        text = _paragraphs_text(asoup, min_len=40)
                        if text:
                            break
                    except Exception:
                        continue

    img = extract_image(soup, base_url=base_url)

    return {"title": title or "", "content": text or "", "image_url": img}


def extract_kun(html: str, base_url: Optional[str] = None) -> dict:
    """Extract article fields from kun.uz pages."""
    soup = BeautifulSoup(html, "lxml")
    title_tag = soup.find("h1")
    title = title_tag.get_text(strip=True) if title_tag else ""

    # prefer explicit kun container classes, then fall back to generic/article
    content_div = (
        soup.find("div", class_="news-inner__content-page")
        or soup.find("div", class_="content")
        or soup.find("div", class_="article__content")
        or soup.find("div", class_="post-content")
        or soup.find("article")
    )
    # kun often has shorter paragraphs; allow smaller min_len
    text = _paragraphs_text(content_div, min_len=20)

    # fallback: try JSON-LD or embedded/escaped HTML in scripts (similar to daryo)
    if not text:
        try:
            import json
            for s in soup.find_all("script", type="application/ld+json"):
                try:
                    jd = json.loads(s.string or s.text)
                except Exception:
                    continue
                if isinstance(jd, dict) and jd.get("articleBody"):
                    ab = jd.get("articleBody") or ""
                    if ab:
                        asoup = BeautifulSoup(ab, "lxml")
                        text = _paragraphs_text(asoup, min_len=20)
                        if text:
                            break
                if isinstance(jd, list):
                    for item in jd:
                        if isinstance(item, dict) and item.get("articleBody"):
                            ab = item.get("articleBody") or ""
                            asoup = BeautifulSoup(ab, "lxml")
                            text = _paragraphs_text(asoup, min_len=20)
                            if text:
                                break
                    if text:
                        break
        except Exception:
            pass

    if not text:
        # heuristic: choose the tag that contains the most <p> text (covers changed layouts)
        best_tag = None
        best_len = 0
        for tag in soup.find_all():
            ps = tag.find_all('p')
            if not ps:
                continue
            total = sum(len(p.get_text(strip=True)) for p in ps)
            if total > best_len:
                best_len = total
                best_tag = tag
        if best_tag and best_len >= 80:
            text = _paragraphs_text(best_tag, min_len=20)

    if not text:
        # Try to recover article HTML from Nuxt/SSR serialized state
        def _extract_json_from_script(script_text: str) -> Optional[dict]:
            if not script_text:
                return None
            # direct JSON blob in script tag with id __NUXT__
            try:
                # some pages have a <script id="__NUXT__" type="application/json">...
                j = json.loads(script_text)
                return j
            except Exception:
                pass

            # window.__NUXT__ = {...}; pattern
            m = re.search(r"window\.__NUXT__\s*=\s*(\{.*?\})\s*;", script_text, flags=re.DOTALL)
            if m:
                js = m.group(1)
                try:
                    return json.loads(js)
                except Exception:
                    # try to extract balanced braces to be more robust
                    start = m.start(1)
            else:
                # fallback: locate first '{' after '__NUXT__'
                idx = script_text.find("__NUXT__")
                if idx != -1:
                    bidx = script_text.find("{", idx)
                    if bidx != -1:
                        # simple balanced-brace extractor that ignores braces inside strings
                        s = script_text
                        i = bidx
                        depth = 0
                        in_str = None
                        esc = False
                        while i < len(s):
                            ch = s[i]
                            if in_str:
                                if esc:
                                    esc = False
                                elif ch == "\\":
                                    esc = True
                                elif ch == in_str:
                                    in_str = None
                            else:
                                if ch == '"' or ch == "'":
                                    in_str = ch
                                elif ch == '{':
                                    depth += 1
                                elif ch == '}':
                                    depth -= 1
                                    if depth == 0:
                                        try:
                                            candidate = s[bidx: i + 1]
                                            return json.loads(candidate)
                                        except Exception:
                                            break
                            i += 1
            return None

        def _find_html_in_obj(obj) -> Optional[str]:
            if obj is None:
                return None
            if isinstance(obj, str):
                # unicode-escaped HTML fragments sometimes appear (e.g. \u003Cp)
                if "\\u003C" in obj:
                    try:
                        dec = bytes(obj, "utf-8").decode("unicode_escape")
                        asoup = BeautifulSoup(dec, "lxml")
                        txt = _paragraphs_text(asoup, min_len=20)
                        if txt:
                            return txt
                    except Exception:
                        pass
                # plain HTML string
                if "<p" in obj or "<div" in obj:
                    asoup = BeautifulSoup(obj, "lxml")
                    txt = _paragraphs_text(asoup, min_len=20)
                    if txt:
                        return txt
                # long plain text
                if len(obj or "") >= 200:
                    return obj
                return None

            if isinstance(obj, dict):
                # prioritize common keys
                for key in ("article", "post", "news", "content", "body", "articleBody", "text"):
                    if key in obj:
                        found = _find_html_in_obj(obj[key])
                        if found:
                            return found
                # otherwise recurse
                for v in obj.values():
                    found = _find_html_in_obj(v)
                    if found:
                        return found
                return None

            if isinstance(obj, list):
                for item in obj:
                    found = _find_html_in_obj(item)
                    if found:
                        return found
                return None

        for s in soup.find_all("script"):
            src = s.string or s.text or ""
            if not src:
                continue
            try:
                jd = _extract_json_from_script(src)
            except Exception:
                jd = None
            if jd:
                # nuxt structure often stores page data under 'data' key
                candidate = None
                if isinstance(jd, dict) and "data" in jd:
                    candidate = _find_html_in_obj(jd.get("data"))
                if not candidate:
                    candidate = _find_html_in_obj(jd)
                if candidate:
                    text = candidate
                    break

    img = extract_image(soup, base_url=base_url)

    return {"title": title or "", "content": text or "", "image_url": img}
