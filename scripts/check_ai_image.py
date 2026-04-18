#!/usr/bin/env python3
"""scripts/check_ai_image.py
Простой скрипт: печатает запись ai_news.id и поле image_urls как JSON.
"""
import os
import asyncio
import json
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set")
        return
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, future=True)
    try:
        async with engine.connect() as conn:
            r = await conn.execute(text("SELECT id, image_urls FROM ai_news WHERE id = :id"), {"id": 491})
            row = r.mappings().first()
            print(json.dumps(row, ensure_ascii=False, default=str))
    finally:
        await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
