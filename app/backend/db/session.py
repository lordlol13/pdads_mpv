from collections.abc import AsyncGenerator

import os
import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.backend.core.config import settings

logger = logging.getLogger(__name__)

# Configure pooling: avoid NullPool (no pooling) for Postgres/production.
# Use NullPool for SQLite or explicit test environments where pooling may cause
# issues (in-memory DBs, short-lived processes).
pool_kwargs: dict = {
    "echo": False,
    "pool_pre_ping": True,  # Verify connections before use
    "pool_recycle": 300,    # Recycle connections after 5 minutes (Railway-safe)
    "future": True
}
db_url = (settings.DATABASE_URL or "").lower()
if "sqlite" in db_url or (settings.APP_ENV or "").lower() == "test":
    pool_kwargs["poolclass"] = NullPool

# When running inside a worker process (e.g. Railway service name containing
# 'worker'), prefer NullPool to avoid asyncpg connections being reused across
# different asyncio event loops created per task, which can lead to
# "Future attached to a different loop" errors. This is a pragmatic fix for
# hosted worker processes; in high-throughput setups consider using a proper
# long-running event loop strategy instead.
try:
    railway_service = os.environ.get("RAILWAY_SERVICE_NAME", "") or ""
    if railway_service and "worker" in railway_service.lower():
        pool_kwargs.setdefault("poolclass", NullPool)
except Exception:
    pass

# FIX: Ensure UTF-8 encoding for PostgreSQL
if "postgres" in db_url:
    pool_kwargs["connect_args"] = {"server_settings": {"client_encoding": "utf8"}}

# PRODUCTION FIX: No SQLite fallback — fail safely with None engine
def _validate_database_url(url: str | None) -> bool:
    """Validate DATABASE_URL is set and not empty."""
    if not url or not url.strip():
        return False
    # Must be a proper database URL
    valid_prefixes = ("postgresql+", "postgres://", "mysql+", "mysql://")
    return any(url.lower().startswith(p) for p in valid_prefixes)

_engine_initialized = False

# Initialize engine and sessionmaker eagerly at import time to avoid
# Celery worker startup races where SessionLocal would be None.
try:
    if not _validate_database_url(settings.DATABASE_URL):
        raise RuntimeError("Invalid DATABASE_URL")
    print(f"[STARTUP] Creating DB engine with pool_recycle=300s using {settings.DATABASE_URL[:60]}...")
    engine = create_async_engine(settings.DATABASE_URL, **pool_kwargs)
    SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    _engine_initialized = True
    logger.info("[STARTUP] Database engine and SessionLocal created at import time")
except Exception as e:
    logger.exception(f"[STARTUP] Failed to initialize DB engine/session at import time: {e}")
    # Fail fast — SessionLocal must never be None in a running system.
    raise


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Get database session — raises RuntimeError if DB is unavailable."""
    if 'SessionLocal' not in globals() or SessionLocal is None:
        raise RuntimeError("SessionLocal is not initialized")
    async with SessionLocal() as session:
        yield session
