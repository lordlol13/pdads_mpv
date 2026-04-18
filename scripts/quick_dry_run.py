import os
import sys
import asyncio
import json
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.backend.services.media_service import fetch_media_urls

async def main():
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        print('DATABASE_URL not set')
        return
    engine = create_async_engine(db_url)
    ai_id = int(sys.argv[1]) if len(sys.argv) > 1 else 491
    
    async with engine.connect() as conn:
        r = await conn.execute(text('SELECT id, final_title, category FROM ai_news WHERE id = :id'), {'id': ai_id})
        row = r.mappings().first()
        if not row:
            print(f'ai_news {ai_id} not found')
            return
        
        print(f'Fetching images for: {row["final_title"]} (category: {row["category"]})')
        candidates = await fetch_media_urls(topic=row['final_title'])
        print(f'Found {len(candidates)} candidates:')
        for c in candidates:
            print(f'  - {c}')

if __name__ == '__main__':
    asyncio.run(main())
