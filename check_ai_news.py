#!/usr/bin/env python3
"""Simple test to verify pipeline ai_news generation."""

import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:5432@localhost:5432/ai_news_db")

async def check_pipeline():
    print("[TEST] Connecting to database...")
    engine = create_async_engine(DATABASE_URL, echo=False)
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    
    async with SessionLocal() as session:
        # 1. Check pending raw_news
        print("\n=== PENDING RAW_NEWS ===")
        result = await session.execute(text("""
        SELECT id, process_status, title
        FROM raw_news
        WHERE process_status IN ('pending', 'processing', NULL)
        ORDER BY id DESC
        LIMIT 5
        """))
        rows = result.mappings().all()
        print(f"Found {len(rows)} pending records:")
        for row in rows:
            print(f"  id={row['id']:4d} status={str(row['process_status']):10s} title={row['title'][:50]}")
        
        if not rows:
            print("[ERROR] No pending records to process!")
            await engine.dispose()
            return False
        
        # 2. Check if any ai_news were created for these raw_news
        raw_ids = [row['id'] for row in rows]
        print(f"\n=== AI_NEWS FOR THESE RAW_NEWS ===")
        placeholders = ','.join([f":{i}" for i in range(len(raw_ids))])
        query = f"""
        SELECT COUNT(*) as count FROM ai_news
        WHERE raw_news_id IN ({placeholders})
        """
        params = {str(i): raw_ids[i] for i in range(len(raw_ids))}
        result = await session.execute(text(query), params)
        count = result.scalar()
        print(f"ai_news records: {count}")
        
        # 3. Show status breakdown
        print(f"\n=== STATUS BREAKDOWN ===")
        result = await session.execute(text("""
        SELECT process_status, COUNT(*) as count
        FROM raw_news
        GROUP BY process_status
        ORDER BY count DESC
        """))
        for row in result.mappings():
            status = row['process_status'] or 'NULL'
            print(f"  {status:15s}: {row['count']:4d}")
    
    await engine.dispose()
    return count > 0

if __name__ == "__main__":
    try:
        success = asyncio.run(check_pipeline())
        if success:
            print("\n✅ Pipeline appears to be working!")
        else:
            print("\n❌ No AI_NEWS found for pending raw_news")
        exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        exit(1)
