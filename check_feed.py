import asyncio
from app.backend.db.session import SessionLocal
from app.backend.core.security import create_access_token
from sqlalchemy import text

async def check_feed():
    async with SessionLocal() as session:
        # Get first user
        result = await session.execute(text('SELECT id, email FROM users LIMIT 1'))
        user = result.mappings().first()
        
        if not user:
            print('No users found!')
            return
            
        print(f'User: ID={user.id}, email={user.email}')
        
        # Create token
        from app.backend.core.config import settings
        token = create_access_token(
            payload={"sub": str(user.id)},
            secret_key=settings.JWT_SECRET_KEY,
            algorithm="HS256",
            expires_minutes=30
        )
        print(f'Token: {token[:50]}...')
        print()
        
        # Now call feed API with token
        import requests
        headers = {'Authorization': f'Bearer {token}'}
        
        print('=== Testing /api/feed/me ===')
        response = requests.get('http://localhost:8000/api/feed/me?limit=5', headers=headers)
        print(f'Status: {response.status_code}')
        
        if response.status_code == 200:
            data = response.json()
            print(f'Feed items: {len(data)}')
            for item in data:
                title = item.get('final_title', 'N/A')[:60]
                print(f"  - ID {item.get('ai_news_id')}: {title}...")
                print(f"    ai_score: {item.get('ai_score')}, saved: {item.get('saved')}")
        else:
            print(f'Error: {response.text}')

if __name__ == '__main__':
    asyncio.run(check_feed())
