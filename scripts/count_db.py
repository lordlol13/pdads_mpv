from __future__ import annotations
import asyncio
from app.backend.db.session import SessionLocal
from sqlalchemy import text

async def main():
    async with SessionLocal() as session:
        n = await session.execute(text("SELECT count(*) FROM raw_news"))
        a = await session.execute(text("SELECT count(*) FROM advertisements"))
        print(f"raw_news: {n.scalar()}")
        print(f"advertisements: {a.scalar()}")

if __name__ == '__main__':
    asyncio.run(main())
