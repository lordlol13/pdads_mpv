import httpx, re
r = httpx.get('https://daryo.uz/_nuxt/D3jSz-M8.js', timeout=30.0)
text = r.text
with open('scripts/D3jSz-M8.js','w',encoding='utf-8') as f:
    f.write(text)
snips = []
for m in re.finditer(r"eb\((?:'|\")([^'\"]+)(?:'|\")\)", text):
    s = max(0, m.start()-200)
    e = m.end()+200
    snips.append(text[s:e])
with open('scripts/eb_snippets.txt','w',encoding='utf-8') as fh:
    fh.write('\n\n'.join(snips))
print('wrote snippets count', len(snips))
