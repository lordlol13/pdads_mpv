#!/usr/bin/env python3
"""Check the raw_news table constraint definition"""
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
        # Get CHECK constraint definition
        query = """
        SELECT constraint_name, constraint_definition
        FROM information_schema.constraint_column_usage ccu
        JOIN information_schema.check_constraints cc 
          ON ccu.constraint_name = cc.constraint_name
        WHERE ccu.table_name = 'raw_news' AND cc.constraint_name LIKE '%process_status%'
        """
        
        result = await session.execute(text(query))
        rows = result.fetchall()
        
        if rows:
            for row in rows:
                print(f"Constraint: {row[0]}")
                print(f"Definition: {row[1]}")
        else:
            # Alternative query
            query2 = """
            SELECT constraint_name, check_clause
            FROM information_schema.table_constraints tc
            JOIN information_schema.check_constraints cc
              USING (constraint_catalog, constraint_schema, constraint_name)
            WHERE tc.table_name = 'raw_news'
            AND tc.constraint_type = 'CHECK'
            """
            
            result2 = await session.execute(text(query2))
            rows2 = result2.fetchall()
            
            for row in rows2:
                print(f"Constraint: {row[0]}")
                print(f"Definition: {row[1]}")
    
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(main())
