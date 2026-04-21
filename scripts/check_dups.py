#!/usr/bin/env python3
from __future__ import annotations
import asyncio
import json
from app.backend.db.session import SessionLocal
from sqlalchemy import text

async def main():
    async with SessionLocal() as session:
        q = text("SELECT source_url, COUNT(*) AS cnt FROM raw_news GROUP BY source_url HAVING COUNT(*) > 1")
        res = await session.execute(q)
        rows = [dict(r) for r in res.mappings().all()]
        with open('scripts/db_duplicates.json', 'w', encoding='utf-8') as fh:
            json.dump(rows, fh, ensure_ascii=False, indent=2)

if __name__ == '__main__':
    asyncio.run(main())
