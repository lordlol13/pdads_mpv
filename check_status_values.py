#!/usr/bin/env python3
"""Check what process_status values currently exist in raw_news"""
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import os

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:5432@localhost:5432/ai_news_db")

async def main():
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Get all distinct process_status values
        query = """
        SELECT DISTINCT process_status, COUNT(*) as count
        FROM raw_news
        GROUP BY process_status
        ORDER BY count DESC
        """
        
        result = await session.execute(text(query))
        rows = result.fetchall()
        
        print("Process status distribution:")
        for row in rows:
            print(f"  '{row[0]}': {row[1]} records")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
