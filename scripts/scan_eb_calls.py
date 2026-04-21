import httpx, re
r = httpx.get('https://daryo.uz/_nuxt/D3jSz-M8.js', timeout=30.0)
text = r.text
pattern = re.compile(r"eb\((?:'|\")([^'\"]+)(?:'|\")\)")
calls = pattern.findall(text)
print('found', len(calls), 'eb calls')
for c in calls[:200]:
    print('-', c)
