#!/usr/bin/env python3
"""Check which records are in 'processing' status"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import os

# Environment setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:5432@localhost:5432/ai_news_db")

async def main():
    """Check stuck records in 'processing' status"""
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Find records stuck in 'processing' status
        query = """
        SELECT id, process_status, title
        FROM raw_news
        WHERE process_status = 'processing'
        ORDER BY id DESC
        LIMIT 30
        """
        
        result = await session.execute(text(query))
        rows = result.fetchall()
        
        print(f"Found {len(rows)} records in 'processing' status:")
        for row in rows:
            print(f"  id={row[0]} status={row[1]} title={row[2][:50]}")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
