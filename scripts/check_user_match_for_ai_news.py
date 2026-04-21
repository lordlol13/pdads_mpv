#!/usr/bin/env python3
"""
scripts/check_user_match_for_ai_news.py
По `ai_news_id` показывает статистику совпадений пользователей по фильтрам target_persona.
Usage: railway run python scripts/check_user_match_for_ai_news.py 491
"""
import os
import sys
import asyncio
import argparse
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    ai_id = int(sys.argv[1]) if len(sys.argv) > 1 else 491
    parser = argparse.ArgumentParser(description="Показывает статистику совпадений пользователей по фильтрам target_persona.")
    parser.add_argument("ai_news_id", type=int, nargs="?", default=491, help="ID новости в таблице ai_news")
    args = parser.parse_args()
    
    ai_id = args.ai_news_id
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
            # load ai_news row
            r = await conn.execute(text("SELECT id, target_persona FROM ai_news WHERE id = :id"), {"id": ai_id})
            row = r.fetchone()
            if not row:
                print(f"ai_news id={ai_id} not found")
                return 0
            target_persona = (row._mapping.get("target_persona") or "")
            print(f"ai_news.id={ai_id}, target_persona='{target_persona}'")

            parts = [p.strip() for p in target_persona.split("|")]
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
            }

            queries = [
                ("active_users", "SELECT COUNT(*) FROM users WHERE COALESCE(is_active, TRUE) = TRUE", {}),
                ("topic_matches", "SELECT COUNT(*) FROM users WHERE COALESCE(is_active, TRUE) = TRUE AND ((:target_topic = 'general') OR (interests -> 'all_topics') ? :target_topic)", {"target_topic": params['target_topic']}),
                ("profession_matches", "SELECT COUNT(*) FROM users WHERE COALESCE(is_active, TRUE) = TRUE AND lower(coalesce(interests ->> 'profession','')) = :target_profession", {"target_profession": params['target_profession']}),
                ("geo_matches", "SELECT COUNT(*) FROM users WHERE COALESCE(is_active, TRUE) = TRUE AND lower(coalesce(location,'')) LIKE :target_geo_like", {"target_geo_like": params['target_geo_like']}),
                ("country_matches", "SELECT COUNT(*) FROM users WHERE COALESCE(is_active, TRUE) = TRUE AND upper(coalesce(country_code,'')) = :target_country_code", {"target_country_code": params['target_country_code']}),
                ("combined_matches", 
                 "SELECT COUNT(*) FROM users u WHERE COALESCE(u.is_active, TRUE) = TRUE "
                 "AND ((:target_topic = 'general') OR (u.interests -> 'all_topics') ? :target_topic) "
                 "AND (:target_profession = '' OR lower(coalesce(u.interests ->> 'profession','')) = :target_profession) "
                 "AND (:target_geo = '' OR lower(coalesce(u.location,'')) LIKE :target_geo_like) "
                 "AND (:target_country_code = '' OR upper(coalesce(u.country_code,'')) = :target_country_code) "
                 "AND NOT EXISTS (SELECT 1 FROM user_feed uf WHERE uf.user_id = u.id AND uf.ai_news_id = :ai_news_id)",
                 {"target_topic": params['target_topic'], "target_profession": params['target_profession'], "target_geo": params['target_geo'], "target_geo_like": params['target_geo_like'], "target_country_code": params['target_country_code'], "ai_news_id": ai_id}
                ),
            ]

            for key, q, qparams in queries:
                res = await conn.execute(text(q), qparams)
                cnt = res.scalar_one()
                print(f"{key}: {cnt}")

    except Exception:
        import traceback
        traceback.print_exc()
        return 3
    finally:
        await engine.dispose()
    return 0

if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
