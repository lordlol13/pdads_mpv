"""Simple CLI to run the async feed ingester.

Usage:
    python scripts/ingest_feeds.py
"""
from __future__ import annotations

import asyncio
import sys

from app.backend.db.session import SessionLocal
from app.backend.services.feed_fetcher import ingest_many
from app.backend.core.logging import ContextLogger


logger = ContextLogger(__name__)


async def main() -> int:
    async with SessionLocal() as session:
        logger.info("Starting ingest run")
        summary = await ingest_many(session)
        logger.info("Ingest summary", summary=summary)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        sys.exit(1)
