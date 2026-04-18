#!/usr/bin/env python3
"""scripts/apply_selected_images_dry_run.py
Dry-run: compute selected `image_urls` for ai_news ids and print the UPDATE SQL (no commit).
Usage: python scripts/apply_selected_images_dry_run.py [ai_news_id ...]
Add `--apply` to actually execute updates (requires DATABASE_URL in env).
"""
from __future__ import annotations

import os
import sys
import asyncio
from pathlib import Path
from typing import List

# ensure project root is importable
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

# import project helpers
try:
    from app.backend.services.media_service import fetch_media_urls
except Exception as e:
    print("Failed to import project media helpers:", e)
    raise


async def _compute_for_ai(engine, ai_id: int, do_apply: bool) -> None:
    async with engine.connect() as conn:
        r = await conn.execute(text("SELECT id, image_urls, final_title, final_text, category, target_persona FROM ai_news WHERE id = :id"), {"id": ai_id})
        row = r.mappings().first()
        if not row:
            print(f"ai_news id={ai_id} not found")
            return

        print(f"ai_news: id={ai_id} title={row.get('final_title')!r} category={row.get('category')!r}")
        # call project media selector
        candidates = await fetch_media_urls(topic=str(row.get("final_title") or ""), # 
            
            
            
            
        )

        print(f"selected {len(candidates)} candidates")
        for i, u in enumerate(candidates):
            print(f"  [{i}] {u}")

        # prepare SQL
        import json
        new_json = json.dumps(candidates, ensure_ascii=False)
        update_sql = "UPDATE ai_news SET image_urls = :urls WHERE id = :id"
        print("--- UPDATE SQL (dry-run) ---")
        print(update_sql)
        print("params:", {"id": ai_id, "urls": new_json})

        if do_apply:
            print("Applying update to DB...")
            await conn.execute(text(update_sql), {"id": ai_id, "urls": new_json})
            await conn.commit()
            print("Applied.")


async def main(argv: List[str]):
    do_apply = False
    ids: List[int] = []
    for a in argv[1:]:
        if a in {"--apply", "-a"}:
            do_apply = True
        else:
            try:
                ids.append(int(a))
            except Exception:
                pass

    if not ids:
        ids = [491]

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL not set in environment. Aborting.")
        return 2

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, future=True)
    try:
        for ai in ids:
            await _compute_for_ai(engine, ai, do_apply)
    finally:
        await engine.dispose()


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main(sys.argv)))
