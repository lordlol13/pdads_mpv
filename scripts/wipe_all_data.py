import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

DB_URL = 'sqlite+aiosqlite:///./dev.db'

target_tables = [
    'ai_news',
    'raw_news',
    'users',
    'registration_verifications',
    'password_reset_requests',
]

async def wipe():
    engine = create_async_engine(DB_URL, echo=False)
    async with engine.begin() as conn:
        for table in target_tables:
            try:
                await conn.execute(text(f'DELETE FROM {table};'))
            except Exception as e:
                print(f'Could not wipe {table}:', e)
    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(wipe())
