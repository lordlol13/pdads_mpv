import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:5432@localhost:5432/ai_news_db')
    for table in ['users', 'raw_news', 'ai_news', 'user_feed']:
        count = await conn.fetchval(f'select count(*) from {table}')
        print(table, count)
    await conn.close()

asyncio.run(main())
