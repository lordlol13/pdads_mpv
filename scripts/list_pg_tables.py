import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:5432@localhost:5432/ai_news_db')
    rows = await conn.fetch("select tablename from pg_tables where schemaname='public' order by tablename")
    print([row['tablename'] for row in rows])
    await conn.close()

asyncio.run(main())
