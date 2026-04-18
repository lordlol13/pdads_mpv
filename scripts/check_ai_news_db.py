#!/usr/bin/env python3
"""
scripts/check_ai_news_db.py
Выводит последние записи из `ai_news` для указанного raw_news_id.
Usage: python scripts/check_ai_news_db.py [raw_news_id]
"""
import os
import sys
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    raw_id = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set in environment.")
        return 2
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, future=True)
    try:
        async with engine.connect() as conn:
            q = text(
                "SELECT id, final_title, ai_score, image_urls, created_at "
                "FROM ai_news WHERE raw_news_id = :raw_id ORDER BY id DESC LIMIT 10"
            )
            res = await conn.execute(q, {"raw_id": raw_id})
            rows = res.fetchall()
            if not rows:
                print(f"No ai_news rows for raw_news_id={raw_id}")
            else:
                for row in rows:
                    m = dict(row._mapping)
                    print(f"- id={m.get('id')}, ai_score={m.get('ai_score')}, title={m.get('final_title')}")
    except Exception:
        import traceback
        traceback.print_exc()
        return 3
    finally:
        await engine.dispose()
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
