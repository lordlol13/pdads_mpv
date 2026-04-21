import asyncio
import json
from datetime import datetime
from decimal import Decimal
from app.backend.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

def json_serial(obj):
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    raise TypeError(f"Type {type(obj)} not serializable")

async def main():
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        users = await conn.execute(
            text("select id, email, username, password_hash, created_at from users order by created_at desc limit 5")
        )
        users_rows = [dict(r) for r in users.mappings().all()]

        regs = await conn.execute(
            text("select id, username, email, is_verified, consumed_at, created_at from registration_verifications order by created_at desc limit 5")
        )
        regs_rows = [dict(r) for r in regs.mappings().all()]

        raw = await conn.execute(
            text("SELECT id, title, source_url, left(raw_text, 1000) AS raw_text_snippet, created_at, process_status FROM raw_news ORDER BY id DESC LIMIT 5")
        )
        raw_rows = [dict(r) for r in raw.mappings().all()]

        ai = await conn.execute(
            text("SELECT id, raw_news_id, final_title, left(final_text, 1000) AS final_text_snippet, category, ai_score FROM ai_news ORDER BY id DESC LIMIT 5")
        )
        ai_rows = [dict(r) for r in ai.mappings().all()]

    await engine.dispose()
    out = {
        "recent_users": users_rows,
        "recent_regs": regs_rows,
        "raw_news": raw_rows,
        "ai_news": ai_rows,
    }
    payload = json.dumps(out, ensure_ascii=False, indent=2, default=json_serial)
    # write to file with UTF-8 to avoid console encoding issues
    with open('scripts/inspect_db_out.json', 'w', encoding='utf-8') as fh:
        fh.write(payload)
    print('WROTE: scripts/inspect_db_out.json')

if __name__ == "__main__":
    asyncio.run(main())
