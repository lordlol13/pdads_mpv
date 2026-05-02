#!/usr/bin/env python
"""Check and create test user in database"""
import asyncio
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

DATABASE_URL = "postgresql+asyncpg://postgres:password@localhost:5432/ai_news_db"

async def check_and_create_user():
    engine = create_async_engine(DATABASE_URL)
    
    try:
        async with engine.begin() as conn:
            # Check existing users
            result = await conn.execute(text('SELECT COUNT(*) FROM public.user'))
            count = result.scalar()
            print(f'✓ Users in database: {count}')
            
            # List first 5 users
            result = await conn.execute(text('SELECT id, username, email FROM public.user LIMIT 5'))
            users = result.fetchall()
            if users:
                print('\nExisting users:')
                for user in users:
                    print(f'  - {user[1]} ({user[2]})')
            
            if count == 0:
                print('\n⚠ No users found. This is expected for a fresh database.')
                print('Users will be created during registration process.')
    
    finally:
        await engine.dispose()

if __name__ == "__main__":
    asyncio.run(check_and_create_user())
