#!/usr/bin/env python3
import json
import urllib.request
import urllib.error
import sys
import os

url = 'https://pdadsmpv-production.up.railway.app/api/llm/generate_article'
payload = {
    "title": "HUMO — National AI Hackathon ishtiroki haqida qisqacha",
    "raw_text": "Тестовый текст для генерации статьи",
    "category": "news",
    "target_persona": "general",
}

def main():
    # API key can be passed as first CLI arg, or via INTERNAL_API_KEY env var
    key = None
    if len(sys.argv) > 1 and sys.argv[1].strip():
        key = sys.argv[1].strip()
    else:
        key = os.environ.get('INTERNAL_API_KEY')

    if not key:
        print('ERROR: INTERNAL_API_KEY not provided. Pass as arg or set INTERNAL_API_KEY env var.')
        sys.exit(2)

    data = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(url, data=data, headers={'Content-Type': 'application/json', 'X-Internal-Api-Key': key})
    try:
        resp = urllib.request.urlopen(req, timeout=120)
        print(resp.status)
        body = resp.read().decode('utf-8')
        print(body)
    except urllib.error.HTTPError as e:
        print('HTTPERROR', e.code)
        try:
            print(e.read().decode())
        except Exception:
            pass
        sys.exit(1)
    except Exception as e:
        print('ERROR', e)
        sys.exit(1)

if __name__ == '__main__':
    main()
