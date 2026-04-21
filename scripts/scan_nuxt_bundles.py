import httpx
from bs4 import BeautifulSoup

html_path = 'scripts/_daryo_sample.html'
with open(html_path, 'r', encoding='utf-8') as fh:
    html = fh.read()

soup = BeautifulSoup(html, 'lxml')
script_srcs = [s.get('src') for s in soup.find_all('script') if s.get('src')]
script_srcs = [s for s in script_srcs if s.startswith('/_nuxt/')]
print('found', len(script_srcs), 'nuxt scripts')

base = 'https://daryo.uz'
for src in script_srcs[:20]:
    url = base + src
    try:
        r = httpx.get(url, timeout=15.0)
        print('\n---', url, 'status', r.status_code)
        txt = r.text
        if 'api/v1/site' in txt:
            print('contains api/v1/site')
        if 'data.daryo.uz' in txt:
            print('contains data.daryo.uz')
        if 'window.__NUXT__' in txt:
            print('contains window.__NUXT__')
        for keyword in ['apiUrl', 'api/v1', 'data.daryo.uz', 'fetch(', 'axios', 'window.__NUXT__']:
            if keyword in txt:
                print('keyword', keyword, 'found')
        # print a small snippet around api if present
        idx = txt.find('api/v1')
        if idx != -1:
            start = max(0, idx-200)
            print(txt[start:idx+200])
    except Exception as e:
        print('failed fetch', url, e)
