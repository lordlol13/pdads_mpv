#!/usr/bin/env python3
"""scripts/list_user_matches_for_ai_news.py
List sample users matching the strict/relaxed/fallback queries for a given ai_news id.
Usage: python scripts/list_user_matches_for_ai_news.py [ai_news_id] [limit]
"""
from __future__ import annotations

import os
import sys
import asyncio
from pathlib import Path
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text


async def main():
    ai_id = int(sys.argv[1]) if len(sys.argv) > 1 else 491
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20

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

    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+asyncpg://", 1)
    elif db_url.startswith("postgresql://") and not db_url.startswith("postgresql+asyncpg://"):
        db_url = db_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    engine = create_async_engine(db_url, future=True)

    try:
        async with engine.connect() as conn:
            r = await conn.execute(text("SELECT id, target_persona, category, final_title FROM ai_news WHERE id = :id"), {"id": ai_id})
            row = r.mappings().first()
            if not row:
                print(f"ai_news id={ai_id} not found")
                return 1

            tp = row.get("target_persona") or ""
            cat = row.get("category") or ""
            title = row.get("final_title") or ""
            print("ai_news:", {"id": ai_id, "target_persona": tp, "category": cat, "title": title})

            parts = [p.strip() for p in (tp or "").split("|")]
            topic = parts[0] if len(parts) > 0 else ""
            profession = parts[1] if len(parts) > 1 else ""
            geo = parts[2] if len(parts) > 2 else ""
            country = parts[3] if len(parts) > 3 else ""

            params = {
                "target_topic": topic or "",
                "target_profession": (profession or "").lower(),
                "target_geo": (geo or "").lower(),
                "target_geo_like": f"%{(geo or '').lower()}%",
                "target_country_code": (country or "").upper(),
                "ai_news_id": ai_id,
                "limit": limit,
            }

            queries = [
                ("existing_user_feed", "SELECT COUNT(*) FROM user_feed WHERE ai_news_id = :ai_news_id", {"ai_news_id": ai_id}),
                ("active_users", "SELECT COUNT(*) FROM users WHERE COALESCE(is_active, TRUE) = TRUE", {}),
                ("strict_sample", 
                 "SELECT id, username, location, country_code, interests FROM users u WHERE COALESCE(u.is_active, TRUE)=TRUE "
                 "AND (:target_topic = 'general' OR (u.interests -> 'all_topics') ? :target_topic) "
                 "AND (:target_profession = '' OR LOWER(COALESCE(u.interests ->> 'profession','')) = :target_profession) "
                 "AND (:target_geo = '' OR LOWER(COALESCE(u.location,'')) LIKE :target_geo_like) "
                 "AND (:target_country_code = '' OR UPPER(COALESCE(u.country_code,'')) = :target_country_code) "
                 "AND NOT EXISTS (SELECT 1 FROM user_feed uf WHERE uf.user_id = u.id AND uf.ai_news_id = :ai_news_id) LIMIT :limit",
                 params),
                ("relaxed_sample",
                 "SELECT id, username, location, country_code, interests FROM users u WHERE COALESCE(u.is_active, TRUE)=TRUE "
                 "AND (:target_topic = 'general' OR ((u.interests -> 'all_topics') ? :target_topic OR (u.interests -> 'topics') ? :target_topic OR (u.interests -> 'custom_topics') ? :target_topic OR LOWER(COALESCE(u.interests::text,'')) LIKE ('%' || :target_topic || '%'))) "
                 "AND (:target_profession = '' OR LOWER(COALESCE(u.interests ->> 'profession','')) = :target_profession) "
                 "AND (:target_geo = '' OR LOWER(COALESCE(u.location,'')) LIKE :target_geo_like) "
                 "AND (:target_country_code = '' OR UPPER(COALESCE(u.country_code,'')) = :target_country_code) "
                 "AND NOT EXISTS (SELECT 1 FROM user_feed uf WHERE uf.user_id = u.id AND uf.ai_news_id = :ai_news_id) LIMIT :limit",
                 params),
                ("fallback_sample",
                 "SELECT id, username, location, country_code, interests FROM users u WHERE COALESCE(u.is_active, TRUE)=TRUE "
                 "AND ((:target_profession != '' AND LOWER(COALESCE(u.interests ->> 'profession','')) = :target_profession) OR (:target_geo != '' AND LOWER(COALESCE(u.location,'')) LIKE :target_geo_like) OR (:target_country_code != '' AND UPPER(COALESCE(u.country_code,'')) = :target_country_code)) "
                 "AND NOT EXISTS (SELECT 1 FROM user_feed uf WHERE uf.user_id = u.id AND uf.ai_news_id = :ai_news_id) LIMIT :limit",
                 params),
            ]

            for name, q, p in queries:
                try:
                    res = await conn.execute(text(q), p)
                    if name.endswith("_sample"):
                        rows = res.mappings().all()
                        print(f"--- {name} count={len(rows)} up to {limit} ---")
                        for r2 in rows:
                            print({
                                "id": r2.get("id"),
                                "username": r2.get("username"),
                                "location": r2.get("location"),
                                "country": r2.get("country_code"),
                                "interests": (str(r2.get("interests") or "")[:200]),
                            })
                    else:
                        cnt = res.scalar_one()
                        print(f"{name}: {cnt}")
                except Exception as e:
                    print(f"query {name} failed: {e}")

    except Exception:
        import traceback

        traceback.print_exc()
        return 3
    finally:
        await engine.dispose()

    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
