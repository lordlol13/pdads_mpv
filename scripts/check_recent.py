import asyncio
import os
import sys
from sqlalchemy import text

# Ensure current directory is in PYTHONPATH
sys.path.append(os.getcwd())

async def main():
    try:
        from app.backend.db.session import SessionLocal
        async with SessionLocal() as session:
            res = await session.execute(text("SELECT count(*) FROM raw_news WHERE created_at >= now() - interval '10 minutes'"))
            print(res.scalar())
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    asyncio.run(main())
