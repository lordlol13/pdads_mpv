from __future__ import annotations
import asyncio
from app.backend.db.session import SessionLocal
from sqlalchemy import text

async def main():
    async with SessionLocal() as session:
        try:
            res = await session.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))
            tables = [r[0] for r in res.all()]
            print(f"Tables: {tables}")
            
            if 'raw_news' in tables:
                n = await session.execute(text("SELECT count(*) FROM raw_news"))
                print(f"raw_news: {n.scalar()}")
            else:
                print("raw_news table not found")
        except Exception as e:
            print(f"Error: {e}")

if __name__ == '__main__':
    asyncio.run(main())
