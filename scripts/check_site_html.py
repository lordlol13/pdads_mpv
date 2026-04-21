from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
}


def check(url: str):
    print(f"--- CHECK {url} ---")
    try:
        r = httpx.get(url, headers=HEADERS, timeout=15)
        print("status:", r.status_code, "len:", len(r.text))
        soup = BeautifulSoup(r.text, "html.parser")
        anchors = [a.get("href") for a in soup.find_all("a", href=True)][:30]
        print("anchors sample:", anchors)
        meta = soup.find("meta", property="og:title")
        if meta and meta.get("content"):
            print("og:title:", meta.get("content")[:120])
        print("snippet:", r.text[:500].replace('\n', ' '))
    except Exception as e:
        print("fetch error:", e)


if __name__ == '__main__':
    for u in ("https://daryo.uz", "https://kun.uz/news"):
        check(u)
