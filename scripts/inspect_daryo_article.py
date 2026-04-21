from __future__ import annotations

import httpx

URL = "https://daryo.uz/2026/04/21/avtomobilni-oson-tarzda-yangilab-oling-kiada-20-mln-somgacha-foydaga-ega-bolish-bilan-trade-in"

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}


def main():
    r = httpx.get(URL, headers=HEADERS, timeout=20)
    print("status:", r.status_code)
    text = r.text
    # Look for common article container keywords
    keywords = ["post-content", "post__text", "article", "entry-content", "news-body", "article-body", "content"]
    for k in keywords:
        idx = text.find(k)
        print(k, "found:" , idx != -1)
        if idx != -1:
            start = max(0, idx - 200)
            print(text[start: idx + 200].replace('\n', ' '))

    # print small snippet around first <p>
    p_idx = text.find("<p")
    if p_idx != -1:
        print("p snippet:", text[p_idx: p_idx+400].replace('\n',' '))


if __name__ == '__main__':
    main()
