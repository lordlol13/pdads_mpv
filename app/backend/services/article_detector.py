from __future__ import annotations
import re
import json
from urllib.parse import urlparse
from typing import List, Optional, Callable, Awaitable
from bs4 import BeautifulSoup


class ArticleDetector:
    """Набор эвристик для определения, является ли URL/страница статьёй.

    Использует двухуровневый подход:
    1) cheap URL check (быстрая фильтрация)
    2) deep HTML check (JSON-LD, og:type, <article>, длинные <p> и т.п.)
    """

    DATE_RE = re.compile(r"/\d{4}/\d{2}/\d{2}/")
    NEGATIVE_RE = re.compile(
        r"/(list|tag|category|categories|archive|auth|login|register|contacts?|contact|about|reklama|ads|photo|photos|video|videos|gallery|catalog|section|page)(/|$|\?)",
        re.I,
    )

    DOMAIN_RULES = {
        "daryo.uz": {
            "positive": [DATE_RE],
            "negative": [],
        },
        "kun.uz": {
            "positive": [re.compile(r"^/news/"), re.compile(r"/news/\d{4}/\d{2}/\d{2}/")],
            "negative": [re.compile(r"/news/list"), re.compile(r"/news/audio"), re.compile(r"/news/editors-choice"), re.compile(r"/news/time/")],
        },
        "gazeta.uz": {
            "positive": [re.compile(r"/\d{4}/\d{2}/\d{2}/")],
            "negative": [re.compile(r"/ru/$"), re.compile(r"/ru/list"), re.compile(r"/list")],
        },
        "podrobno.uz": {
            "positive": [re.compile(r"/\d{4}/\d{2}/\d{2}/")],
            "negative": [re.compile(r"^/$"), re.compile(r"/cat/"), re.compile(r"/project/")],
        },
        "uznews.uz": {
            "positive": [re.compile(r"/ru/news/\d+"), re.compile(r"/ru/articles/"), re.compile(r"/\d{4}/\d{2}/\d{2}/")],
            "negative": [],
        },
    }

    def is_article_url(self, url: str, source: Optional[str] = None) -> bool:
        if not url:
            return False
        try:
            u = urlparse(url)
        except Exception:
            return False

        path = u.path or "/"

        # 1) явно дата в URL
        if self.DATE_RE.search(path):
            return True

        # 2) доменно-специфичные правила
        netloc = (u.netloc or "").lower()
        if netloc.startswith("www."):
            netloc = netloc[4:]

        for domain, rules in self.DOMAIN_RULES.items():
            if netloc.endswith(domain):
                # negative сначала
                for neg in rules.get("negative", []):
                    if neg.search(path):
                        return False
                for pos in rules.get("positive", []):
                    if pos.search(path):
                        return True

                # простая эвристика для домена: много сегментов и slug-похожая последняя часть
                segments = [s for s in path.split("/") if s]
                if len(segments) >= 3:
                    last = segments[-1]
                    if "-" in last or re.search(r"\d", last) or len(last) > 20:
                        return True
                return False

        # 3) глобальные negative паттерны (категории, списки и т.п.)
        if self.NEGATIVE_RE.search(path):
            return False

        # 4) запасная эвристика: достаточно глубокий путь + заметный slug
        segments = [s for s in path.split("/") if s]
        if len(segments) >= 3:
            last = segments[-1]
            if last and ("-" in last or re.search(r"\d", last) or len(last) > 20):
                return True

        # 5) файлы .html/.htm — считаем статьёй
        if path.endswith(".html") or path.endswith(".htm"):
            return True

        return False

    ARTICLE_JSONLD_TYPES = {"NewsArticle", "Article"}
    BAD_URL_SUBSTRINGS = [
        "editors-choice",
        "/time/",
        "/list",
        "/category",
        "/tag",
        "/tags",
    ]

    def is_bad_article(self, url: Optional[str]) -> bool:
        if not url:
            return False
        u = url.lower()
        for bad in self.BAD_URL_SUBSTRINGS:
            if bad in u:
                return True
        return False

    def has_article_json_ld(self, soup: "BeautifulSoup") -> bool:
        """Проверяет JSON-LD и возвращает True только для явных типов статьи."""
        for tag in soup.find_all("script", type="application/ld+json"):
            txt = tag.string or tag.get_text() or ""
            txt = txt.strip()
            if not txt:
                continue
            try:
                obj = json.loads(txt)
            except Exception:
                continue

            def _has_article(o) -> bool:
                if isinstance(o, dict):
                    t = o.get("@type") or o.get("type")
                    if isinstance(t, str) and t in self.ARTICLE_JSONLD_TYPES:
                        return True
                    if isinstance(t, list):
                        for it in t:
                            if it in self.ARTICLE_JSONLD_TYPES:
                                return True
                    for v in o.values():
                        if _has_article(v):
                            return True
                elif isinstance(o, list):
                    for item in o:
                        if _has_article(item):
                            return True
                return False

            if _has_article(obj):
                return True
        return False

    def score_article_page(self, html: Optional[str], url: Optional[str] = None) -> tuple[int, dict]:
        """Вернёт (score, details). Сигналы:
        +2 JSON-LD Article
        +2 og:type == article
        +1 длинный текст (>1000 символов)
        -2 плохой URL (blacklist)

        Решение: score >= 2 считается статьёй.
        """
        details = {}
        if not html:
            return 0, details
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception:
            soup = BeautifulSoup(html, "html.parser")

        # основной текст страницы
        body_text = soup.get_text(" ", strip=True) or ""
        text_len = len(body_text)
        details["text_len"] = text_len

        score = 0

        # JSON-LD сигнал
        has_json = self.has_article_json_ld(soup)
        details["has_json_ld"] = bool(has_json)
        if has_json:
            score += 2

        # og:type
        og = soup.find("meta", property="og:type") or soup.find("meta", attrs={"name": "og:type"})
        og_content = (og.get("content", "") or "").strip().lower() if og else ""
        details["og_type"] = og_content
        if og_content == "article":
            score += 2

        # длинный текст как слабый сигнал
        if text_len > 1000:
            score += 1

        # плохие URL по списку — штраф
        if url and self.is_bad_article(url):
            details["is_bad_url"] = True
            score -= 2
        else:
            details["is_bad_url"] = False

        details["score"] = score
        return score, details

    def is_article_page(self, html: Optional[str]) -> bool:
        """Deep HTML check: теперь основано на scoring (см. score_article_page)."""
        sc, _ = self.score_article_page(html)
        return sc >= 2

    async def is_valid_article(self, url: str, fetch_html: Callable[..., Awaitable[Optional[str]]], session=None) -> bool:
        """Сначала быстрый check по URL, затем глубокая проверка по HTML (fetch_html должен вернуть HTML или None)."""
        if not self.is_article_url(url):
            return False
        # быстрый анти-фильтр по URL (редакционные и списочные страницы)
        if self.is_bad_article(url):
            return False
        try:
            html = await fetch_html(session, url)
        except Exception:
            html = None
        if not html:
            return False
        return self.is_article_page(html)


__all__ = ["ArticleDetector"]
