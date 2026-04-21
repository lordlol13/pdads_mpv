import asyncio
import os
import sys
from sqlalchemy import text

sys.path.append(os.getcwd())

async def main():
    try:
        from app.backend.db.session import SessionLocal
        async with SessionLocal() as session:
            # Check the last 15 minutes to be sure
            res = await session.execute(text("SELECT id, source_url, created_at FROM raw_news WHERE created_at >= now() - interval '15 minutes' ORDER BY created_at DESC LIMIT 5"))
            rows = res.all()
            if not rows:
                print("No recent records found in the last 15 minutes.")
            for row in rows:
                print(f"ID: {row[0]}, URL: {row[1]}, Created At: {row[2]}")
    except Exception as e:
        print(f"Error: {e}")

if __name__ == '__main__':
    asyncio.run(main())
