#!/usr/bin/env python3
"""
scripts/check_user_feed_db.py
Выводит записи из `user_feed` для указанного ai_news_id.
Usage: python scripts/check_user_feed_db.py [ai_news_id]
"""
import os
import sys
import asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    ai_news_id = int(sys.argv[1]) if len(sys.argv) > 1 else 491
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
            q = text(
                "SELECT user_id, ai_news_id, ai_score, created_at "
                "FROM user_feed WHERE ai_news_id = :aid ORDER BY created_at DESC LIMIT 200"
            )
            res = await conn.execute(q, {"aid": ai_news_id})
            rows = res.fetchall()
            if not rows:
                print(f"No user_feed rows for ai_news_id={ai_news_id}")
            else:
                for r in rows:
                    m = dict(r._mapping)
                    print(f"- user_id={m.get('user_id')}, ai_score={m.get('ai_score')}, created_at={m.get('created_at')}")
    except Exception:
        import traceback
        traceback.print_exc()
        return 3
    finally:
        await engine.dispose()
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
