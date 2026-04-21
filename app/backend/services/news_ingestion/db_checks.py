from __future__ import annotations
import asyncio
import json
from sqlalchemy import text
from app.backend.db.session import engine

async def main() -> int:
    sql = text("""
    SELECT
        i.relname as index_name,
        idx.indisunique as is_unique,
        array_to_string(array_agg(a.attname ORDER BY array_position(idx.indkey, a.attnum)), ",") as columns
    FROM pg_class t
    JOIN pg_index idx ON t.oid = idx.indrelid
    JOIN pg_class i ON i.oid = idx.indexrelid
    JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(idx.indkey)    
    WHERE t.relkind = "r" AND t.relname = "raw_news"
    GROUP BY i.relname, idx.indisunique
    ORDER BY i.relname;
    """.replace('"', "'"))

    try:
        async with engine.connect() as conn:
            res = await conn.execute(sql)
            rows = res.fetchall()
            indexes = []
            for row in rows:
                indexes.append({"index_name": row[0], "is_unique": bool(row[1]), "columns": (row[2] or "")})

            print(json.dumps({"raw_news_indexes": indexes}, ensure_ascii=False, indent=2))
            # quick checks
            has_content_hash_unique = any(("content_hash" in (r["columns"] or "")) and r["is_unique"] for r in indexes)
            has_source_url_unique = any(("source_url" in (r["columns"] or "")) and r["is_unique"] for r in indexes)

            print()
            print("content_hash_unique:", has_content_hash_unique)
            print("source_url_unique:", has_source_url_unique)
            return 0
    except Exception as exc:
        print("ERROR: failed to query pg indexes:", exc)
        import traceback
        traceback.print_exc()
        return 2

if __name__ == "__main__":
    code = asyncio.run(main())
    exit(code)
