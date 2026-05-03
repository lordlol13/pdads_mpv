#!/usr/bin/env python3
"""Reset stuck processing records and verify pipeline readiness."""

import asyncio
from app.backend.db.session import init_engine, SessionLocal
from sqlalchemy import text

async def reset_stuck():
    # Initialize database engine
    await init_engine()
    if SessionLocal is None:
        print("[ERROR] Database not available")
        return
    
    async with SessionLocal() as session:
        # FIX 2: Force reset stuck records
        print("[RESET] Resetting stuck processing records...")
        query = """
        UPDATE raw_news
        SET process_status = 'pending'
        WHERE process_status = 'processing'
        """
        result = await session.execute(text(query))
        reset_count = result.rowcount or 0
        await session.commit()
        print(f'[DB] reset stuck processing records: {reset_count}')
        
        # Verify pending records
        verify = await session.execute(text("SELECT COUNT(*) FROM raw_news WHERE process_status = 'pending'"))
        pending_count = verify.scalar()
        print(f'[DB] total pending records now: {pending_count}')
        
        # Show status breakdown
        breakdown = await session.execute(text("""
        SELECT process_status, COUNT(*) as count
        FROM raw_news
        GROUP BY process_status
        ORDER BY count DESC
        """))
        print("\n[DB] Status breakdown:")
        for row in breakdown.mappings():
            status = row.get('process_status') or 'NULL'
            count = row.get('count', 0)
            print(f"  {status}: {count}")

if __name__ == "__main__":
    asyncio.run(reset_stuck())
