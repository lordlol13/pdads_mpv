import httpx
from bs4 import BeautifulSoup

url = "https://daryo.uz/2026/04/19/trampning-maslahatchilari-ziddiyatli-bayonotlari-sabab-undan-intervyularni-kamaytirishni-soramoqda-wsj"
print('fetching', url)
try:
    r = httpx.get(url, headers={"User-Agent": "pdads_ai_test/1.0 (+https://example)"}, follow_redirects=True, timeout=15.0)
    print('status', r.status_code)
    print('final_url', r.url)
    html = r.text
    with open('scripts/_daryo_sample.html', 'w', encoding='utf-8') as fh:
        fh.write(html)
    soup = BeautifulSoup(html, 'lxml')
    print('title:', soup.title.string if soup.title else None)
    selectors = [
        ".news-section-main-content", ".section-pages__wrapper_content", ".layout-body",
        "div.article-body", "div.article_text", ".article-body", ".post-content", ".entry-content",
        "[itemprop=articleBody]", ".content", ".article-text", ".news-text", "article"
    ]
    candidates = []
    for sel in selectors:
        el = soup.select_one(sel)
        if el:
            candidates.append((sel, el))
    print('candidates found:', len(candidates))
    for i, (sel, c) in enumerate(candidates[:10]):
        t = c.get_text(' ', strip=True)
        print(f'--- candidate {i} selector={sel} classes={c.get("class")} len={len(t)}')
        print(t[:400])
    ps = soup.find_all('p')
    print('p_count', len(ps))
    for i, p in enumerate(ps[:20]):
        txt = p.get_text(' ', strip=True)
        print(f'p[{i}] len={len(txt)} ->', txt[:200])
except Exception as e:
    print('fetch failed', e)
