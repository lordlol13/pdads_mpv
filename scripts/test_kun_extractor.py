from __future__ import annotations

import os
import sys
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

# make project importable
sys.path.insert(0, os.getcwd())

from app.backend.services.news_ingestion.extractors import extract_kun

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Language": "en-US,en;q=0.9"}


def main():
    r = httpx.get("https://kun.uz", headers=HEADERS, timeout=20)
    print("root status:", r.status_code)
    soup = BeautifulSoup(r.text, "html.parser")
    anchors = [a.get('href') for a in soup.find_all('a', href=True)]
    candidates = []
    for h in anchors:
        if '/news/' in h and '-' in (h or ''):
            candidates.append(h)
    if not candidates:
        print('no candidates found')
        return

    href = candidates[0]
    full = urljoin('https://kun.uz', href)
    print('testing url:', full)
    r2 = httpx.get(full, headers=HEADERS, timeout=20)
    print('article status:', r2.status_code, 'len:', len(r2.text))

    res = extract_kun(r2.text, base_url='https://kun.uz')
    print('title:', res.get('title'))
    content = res.get('content') or ''
    print('content length:', len(content))
    print('content preview:\n', content[:800])
    print('image:', res.get('image_url'))


if __name__ == '__main__':
    main()
