import asyncio
import httpx
from app.backend.services.news_api_service import _parse_rss_payload

async def test():
    async with httpx.AsyncClient(follow_redirects=True) as client:
        try:
            r = await client.get('https://daryo.uz/ru/rss/')
            items = _parse_rss_payload(r.text, 'Daryo', 100)
            print(f"Items found: {len(items)}")
            for i in items[:3]:
                print(f" - {i.get('title')}")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == '__main__':
    asyncio.run(test())
