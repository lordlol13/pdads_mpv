#!/usr/bin/env python3
"""scripts/run_media_for_ai_news.py
Fetch an `ai_news` row and run `fetch_media_urls` to show chosen image URLs.
Usage: python scripts/run_media_for_ai_news.py [ai_news_id]
"""
from __future__ import annotations

import os
import sys
import asyncio
import json
import sys
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import re

# Ensure project root is on sys.path so `app` package can be imported when
# running the script directly from `scripts/`.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


async def main():
    ai_id = int(sys.argv[1]) if len(sys.argv) > 1 else 491

    # Ensure DATABASE_URL present: try env, then .env file
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        env_path = Path(__file__).resolve().parents[1] / ".env"
        if env_path.exists():
            for line in env_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"')
                if k == "DATABASE_URL" and v:
                    os.environ["DATABASE_URL"] = v
                    db_url = v
                    break

    if not db_url:
        print("DATABASE_URL is not set in environment.")
        return 2

    # normalize to asyncpg style
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    # Print a masked representation so we can debug connection issues without exposing the password.
    try:
        from urllib.parse import urlparse

        p = urlparse(db_url)
        display = f"{p.scheme}://{p.username or ''}:***@{p.hostname or ''}:{p.port or ''}/{(p.path or '').lstrip('/')}"
    except Exception:
        display = str(db_url)[:200]
    print("Resolved DATABASE_URL:", display)

    engine = create_async_engine(db_url, future=True)

    try:
        async with engine.connect() as conn:
            q = text(
                """
                SELECT
                    an.id,
                    an.raw_news_id,
                    an.target_persona,
                    an.final_title,
                    an.final_text,
                    an.image_urls,
                    an.category,
                    rn.source_url AS raw_source_url,
                    rn.image_url AS raw_image_url,
                    rn.title AS raw_title
                FROM ai_news an
                LEFT JOIN raw_news rn ON rn.id = an.raw_news_id
                WHERE an.id = :id
                LIMIT 1
                """
            )
            res = await conn.execute(q, {"id": ai_id})
            row = res.mappings().first()
            if not row:
                print(f"ai_news id={ai_id} not found")
                return 1

            data = dict(row)
            print("ai_news row:")
            print(json.dumps({k: (v if not isinstance(v, bytes) else str(v)) for k, v in data.items()}, indent=2, ensure_ascii=False))

            # determine topic
            target_persona = str(data.get("target_persona") or "")
            if target_persona:
                topic = target_persona.split("|")[0]
            else:
                topic = data.get("category") or data.get("final_title") or "general"
            topic = str(topic or "general")

            source_url = data.get("raw_source_url")
            source_image_url = data.get("raw_image_url")

            print(f"Using topic: {topic}")
            print(f"Source URL: {source_url}")
            print(f"Source image URL: {source_image_url}")

            # Import media selection late to avoid unnecessary imports if DB not set
            from app.backend.services.media_service import fetch_media_urls

            print("Calling fetch_media_urls(...)")
            urls = await fetch_media_urls(topic=topic, limit=6, source_url=source_url, source_image_url=source_image_url)

            print("Selected image_urls:")
            print(json.dumps(urls, indent=2, ensure_ascii=False))

    except Exception as exc:
        import traceback

        print("Error while running media selection:")
        traceback.print_exc()
        return 3
    finally:
        await engine.dispose()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
