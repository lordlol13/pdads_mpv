#!/usr/bin/env python3
"""Test pipeline processing directly."""

import asyncio
import logging
import sys
import os
os.environ['CELERY_ALWAYS_EAGER'] = '1'

# Import settings first to initialize celery
from app.backend.core.config import settings

logging.basicConfig(level=logging.INFO, format='%(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

async def test_pipeline():
    try:
        # Import session module which should already have initialized engine from app startup
        from app.backend.db import session as db_session
        
        # Try to get SessionLocal - it might already be initialized by app
        SessionLocal = db_session.SessionLocal
        engine = db_session.engine
        
        # If not yet initialized, initialize now
        if SessionLocal is None or engine is None:
            logger.info("[INIT] SessionLocal is None, calling init_engine...")
            await db_session.init_engine()
            SessionLocal = db_session.SessionLocal
            engine = db_session.engine
        
        if SessionLocal is None:
            print("[ERROR] SessionLocal still unavailable after init")
            return False
        
        logger.info("[INIT] Database ready. SessionLocal=%s", SessionLocal)
        
        # Import here after db is ready
        from app.backend.services.ingestion_service import insert_test_raw_news
        from brain.tasks.pipeline_tasks import _process_raw_news_async
        from sqlalchemy import text
        
        async with SessionLocal() as session:
            # Check pending raw_news
            print("\n=== CHECKING PENDING RAW_NEWS ===")
            result = await session.execute(text("""
            SELECT id, title, process_status 
            FROM raw_news 
            WHERE process_status IN ('pending', 'processing', NULL)
            ORDER BY id DESC
            LIMIT 5
            """))
            rows = result.mappings().all()
            print(f"Found {len(rows)} pending records:")
            for row in rows:
                print(f"  id={row['id']}, status={row['process_status']}, title={row['title'][:50]}")
            
            if not rows:
                print("[TEST] No pending records. Inserting test record...")
                await insert_test_raw_news(session)
                result = await session.execute(text("SELECT MAX(id) as last_id FROM raw_news"))
                last_id = result.scalar()
                print(f"[TEST] Inserted record with id={last_id}")
                rows = [{'id': last_id}]
        
        # Process first pending record
        if rows:
            raw_id = rows[0]['id']
            print(f"\n=== PROCESSING RAW_NEWS ID={raw_id} ===")
            try:
                result = await _process_raw_news_async(raw_id, attempt=1)
                print(f"[RESULT] {result}")
            except Exception as e:
                logger.exception(f"[ERROR] Processing failed: {e}")
                return False
        
        # Check if ai_news was created
        async with SessionLocal() as session:
            print("\n=== CHECKING AI_NEWS ===")
            result = await session.execute(text("""
            SELECT id, raw_news_id, target_persona, final_title
            FROM ai_news
            WHERE raw_news_id = :rid
            """), {"rid": raw_id})
            ai_rows = result.mappings().all()
            print(f"Found {len(ai_rows)} ai_news records for raw_news_id={raw_id}:")
            for row in ai_rows:
                print(f"  id={row['id']}, persona={row['target_persona']}, title={row['final_title'][:50]}")
            
            if len(ai_rows) > 0:
                print("\n✅ SUCCESS: AI_NEWS generated!")
                return True
            else:
                print("\n❌ FAILED: No AI_NEWS generated")
                return False
    except Exception as e:
        logger.exception(f"[FATAL] test_pipeline failed: {e}")
        return False

if __name__ == "__main__":
    success = asyncio.run(test_pipeline())
    exit(0 if success else 1)
