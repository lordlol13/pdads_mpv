import asyncio
from app.backend.db.session import SessionLocal
from sqlalchemy import text

async def main():
    try:
        async with SessionLocal() as session:
            query = "SELECT indexname, indexdef FROM pg_indexes WHERE tablename='raw_news' AND indexname='uq_raw_news_source_url'"
            res = await session.execute(text(query))
            rows = res.fetchall()
            if not rows:
                print("No index 'uq_raw_news_source_url' found on 'raw_news' table.")
            for r in rows:
                print(f"Index: {r[0]}, Definition: {r[1]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    asyncio.run(main())
