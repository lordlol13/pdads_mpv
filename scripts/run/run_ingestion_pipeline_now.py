import asyncio
from sqlalchemy import text
from app.backend.db.session import SessionLocal
from brain.tasks.pipeline_tasks import _schedule_ingestion_batch_async, _process_raw_news_async
from app.backend.services.http_client import close_async_clients


async def main() -> None:
    print('starting ingestion batch...')
    batch = await _schedule_ingestion_batch_async()
    print('ingestion result:', batch)

    async with SessionLocal() as session:
        result = await session.execute(text("""
            SELECT id, process_status
            FROM raw_news
            WHERE process_status IN ('pending', 'failed', 'classified') OR process_status IS NULL
            ORDER BY id ASC
            LIMIT 50
        """))
        raw_ids = [row.id for row in result]

    print('raw_news_to_process:', raw_ids)

    processed = 0
    failed = 0
    for rid in raw_ids:
        try:
            out = await _process_raw_news_async(rid, 1, None)
            print('processed', rid, out.get('status'))
            processed += 1
        except Exception as e:
            print('failed', rid, str(e)[:200])
            failed += 1

    async with SessionLocal() as session:
        counts = {}
        for table in ('raw_news', 'ai_news', 'user_feed'):
            c = await session.execute(text(f"select count(*) from {table}"))
            counts[table] = int(c.scalar() or 0)

    # Best-effort cleanup of shared async HTTP clients to avoid leftover tasks
    try:
        await close_async_clients()
    except Exception:
        pass

    print('final_counts:', counts)
    print('processed_ok:', processed, 'failed:', failed)


asyncio.run(main())
