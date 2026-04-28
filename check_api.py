import requests
import json

# Check ai-news endpoint
print('=== /api/pipeline/ai-news ===')
response = requests.get('http://localhost:8000/api/pipeline/ai-news?limit=3')
if response.status_code == 200:
    data = response.json()
    print(f'Records: {len(data)}')
    for item in data:
        print(f"  ID {item['id']}: {item['final_title'][:50]}... (score: {item['ai_score']})")
else:
    print(f'Error: {response.status_code}')

print()

# Check feed endpoint (need auth token)
print('=== /api/feed/me (no auth) ===')
response = requests.get('http://localhost:8000/api/feed/me?limit=3')
print(f'Status: {response.status_code}')
if response.status_code == 200:
    data = response.json()
    print(f'Feed items: {len(data)}')
    for item in data[:3]:
        print(f"  - {item.get('final_title', 'N/A')[:50]}...")
else:
    print(f'Error: {response.text[:200]}')
