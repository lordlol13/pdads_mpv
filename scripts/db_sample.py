#!/usr/bin/env python3
"""Простой скрипт: вывести 3 последних строки из raw_news для ручной проверки."""
from __future__ import annotations
import asyncio
from app.backend.db.session import SessionLocal
from sqlalchemy import text

async def main():
    async with SessionLocal() as session:
        q = text("SELECT id, title, source_url, LENGTH(COALESCE(raw_text,'')) AS raw_len, image_url, created_at FROM raw_news ORDER BY id DESC LIMIT 3")
        res = await session.execute(q)
        rows = res.mappings().all()
        for r in rows:
            raw_len = r.get('raw_len')
            print(f"id={r.get('id')} url={r.get('source_url')} title={str(r.get('title'))[:120]} raw_len={raw_len} image_url={'yes' if r.get('image_url') else 'no'} created_at={r.get('created_at')}")

if __name__ == '__main__':
    asyncio.run(main())
