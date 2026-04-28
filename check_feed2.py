import asyncio
from app.backend.db.session import SessionLocal
from app.backend.services.feed_service import get_user_feed
from app.backend.core.config import settings

async def check():
    print("Starting feed check...")
    async with SessionLocal() as session:
        print("Session created, calling get_user_feed for user_id=5...")
        try:
            items = await asyncio.wait_for(
                get_user_feed(session, user_id=5, limit=5),
                timeout=30.0
            )
            print(f"SUCCESS: Got {len(items)} items")
            for item in items[:3]:
                title = item.get('final_title', 'N/A')[:50]
                print(f"  - {title}... (ai_score: {item.get('ai_score')})")
        except asyncio.TimeoutError:
            print("TIMEOUT: get_user_feed took longer than 30 seconds!")
        except Exception as e:
            print(f"ERROR: {type(e).__name__}: {e}")

if __name__ == '__main__':
    asyncio.run(check())
