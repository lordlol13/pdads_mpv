import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:5432@localhost:5432/ai_news_db')
    version = await conn.fetchval('select version()')
    print('connected=', bool(version))
    await conn.close()

asyncio.run(main())
