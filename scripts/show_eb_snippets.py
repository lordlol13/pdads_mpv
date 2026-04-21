import httpx, re
r = httpx.get('https://daryo.uz/_nuxt/D3jSz-M8.js', timeout=30.0)
text = r.text
for m in re.finditer(r"eb\((?:'|\")([^'\"]+)(?:'|\")\)", text):
    s = max(0, m.start()-200)
    e = m.end()+200
    print('---', text[s:e])
    print('\n')
