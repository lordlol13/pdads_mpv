#!/usr/bin/env python3
"""
Simple pipeline watcher: counts `ai_news` items created in the last hour.
Run with the project's virtualenv active.
"""
import asyncio
from datetime import datetime, timedelta, timezone
import logging

from sqlalchemy import text

from app.backend.db.session import SessionLocal

LOG = logging.getLogger("pipeline_watcher")


async def check_once() -> int:
    async with SessionLocal() as session:
        bind = session.get_bind()
        dialect = bind.dialect.name

        if dialect == "sqlite":
            # SQLite: fetch recent rows and filter in Python
            result = await session.execute(text("SELECT created_at FROM ai_news ORDER BY created_at DESC LIMIT 1000"))
            rows = [r[0] for r in result.fetchall() if r and r[0]]
            now = datetime.now(timezone.utc)
            cutoff = now - timedelta(hours=1)
            count = sum(1 for dt in rows if dt and dt >= cutoff)
            return int(count)

        # Postgres: use SQL interval
        result = await session.execute(text("SELECT COUNT(*) FROM ai_news WHERE created_at >= NOW() - INTERVAL '1 hour'"))
        count = result.scalar_one_or_none() or 0
        return int(count)


async def main(poll_interval: int = 60):
    logging.basicConfig(level=logging.INFO)
    LOG.info("Starting pipeline watcher (poll_interval=%s)s", poll_interval)
    try:
        while True:
            count = await check_once()
            LOG.info("ai_news created in last hour: %d", count)
            await asyncio.sleep(poll_interval)
    except asyncio.CancelledError:
        LOG.info("Watcher cancelled")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Interrupted")
