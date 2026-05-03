#!/usr/bin/env python3
"""Reset stuck 'processing' records back to 'pending' status"""
import asyncio
import sys
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import text
import os

# Environment setup
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:5432@localhost:5432/ai_news_db")

async def main():
    """Reset stuck records from 'processing' to 'pending'"""
    engine = create_async_engine(DATABASE_URL, echo=False)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    
    async with async_session() as session:
        # Reset records stuck in 'processing' status
        query = """
        UPDATE raw_news
        SET process_status = 'pending',
            error_message = NULL,
            processing_started_at = NULL
        WHERE process_status = 'processing'
        RETURNING id, title
        """
        
        result = await session.execute(text(query))
        rows = result.fetchall()
        
        await session.commit()
        
        print(f"✅ Reset {len(rows)} stuck 'processing' records to 'pending':")
        for row in rows:
            print(f"  id={row[0]} title={row[1][:60]}")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
