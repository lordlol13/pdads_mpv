#!/usr/bin/env python3
from __future__ import annotations
import asyncio
import json
from app.backend.db.session import SessionLocal
from sqlalchemy import text

async def main():
    async with SessionLocal() as session:
        q = text("SELECT id, title, source_url, COALESCE(raw_text,'') AS raw_text, image_url, created_at FROM raw_news ORDER BY id DESC LIMIT 3")
        res = await session.execute(q)
        rows = [dict(r) for r in res.mappings().all()]
        with open("data/debug/db_sample_out.json", "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False, default=str, indent=2)

if __name__ == '__main__':
    asyncio.run(main())
