from __future__ import annotations

import httpx
from bs4 import BeautifulSoup

URL = "https://kun.uz"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def main():
    r = httpx.get(URL, headers=HEADERS, timeout=15)
    print("status:", r.status_code)
    soup = BeautifulSoup(r.text, "html.parser")
    anchors = [a.get('href') for a in soup.find_all('a', href=True)]
    candidates = []
    for h in anchors:
        if '/news/' in h and '-' in h:
            candidates.append(h)
    print('found candidate anchors:', len(candidates))
    for c in candidates[:50]:
        print(c)


if __name__ == '__main__':
    main()
