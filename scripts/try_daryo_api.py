import httpx
from urllib.parse import urlparse, quote

api_base = "https://data.daryo.uz/api/v1/site/"
url = "https://daryo.uz/2026/04/19/trampning-maslahatchilari-ziddiyatli-bayonotlari-sabab-undan-intervyularni-kamaytirishni-soramoqda-wsj/"
path = urlparse(url).path
if not path.endswith('/'):
    path = path + '/'

candidates = [
    "page?path={path}",
    "page?url={url}",
    "pages?path={path}",
    "content?path={path}",
    "resource?path={path}",
    "article?path={path}",
    "article?url={url}",
    "route?path={path}",
    "route?url={url}",
    "item?path={path}",
    "node?path={path}",
    "{path}",
    "oz{path}",
    "ru{path}",
]

print('trying api base', api_base)
for cand in candidates:
    target = api_base + cand.format(path=quote(path), url=quote(url, safe=''))
    try:
        r = httpx.get(target, timeout=10.0)
        print('\n->', target, 'status', r.status_code)
        ct = r.headers.get('content-type','')
        print(' content-type', ct)
        text = r.text[:2000]
        print(' body preview:', text[:800])
        # try json
        try:
            j = r.json()
            keys = list(j.keys()) if isinstance(j, dict) else None
            print(' json keys:', keys)
            # try to find body-like keys
            def find_keys(obj, prefix=''):
                if isinstance(obj, dict):
                    for k, v in obj.items():
                        if isinstance(v, (dict, list)):
                            find_keys(v, prefix + '.' + k)
                        else:
                            if k.lower() in ('body', 'content', 'article', 'text', 'description', 'html'):
                                print(' found', prefix + '.' + k)
                elif isinstance(obj, list):
                    for i, it in enumerate(obj[:3]):
                        find_keys(it, prefix + f'[{i}]')
            find_keys(j)
        except Exception as e:
            print(' not json or parse failed', e)
    except Exception as e:
        print('request failed', e)
