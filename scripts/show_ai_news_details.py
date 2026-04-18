#!/usr/bin/env python3
"""
scripts/show_ai_news_details.py
Выводит все поля строки из `ai_news` по id.
Usage: python scripts/show_ai_news_details.py [ai_news_id]
"""
import os
import sys
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    ai_id = int(sys.argv[1]) if len(sys.argv) > 1 else 491
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set in environment.")
        return 2
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, future=True)
    try:
        async with engine.connect() as conn:
            q = text("SELECT * FROM ai_news WHERE id = :id")
            res = await conn.execute(q, {"id": ai_id})
            row = res.fetchone()
            if not row:
                print(f"ai_news id={ai_id} not found")
                return 0
            m = dict(row._mapping)
            for k, v in m.items():
                print(f"{k}: {v}")
    except Exception:
        import traceback
        traceback.print_exc()
        return 3
    finally:
        await engine.dispose()
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
