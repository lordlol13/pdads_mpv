from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.backend.core.config import settings

# Configure pooling: avoid NullPool (no pooling) for Postgres/production.
# Use NullPool for SQLite or explicit test environments where pooling may cause
# issues (in-memory DBs, short-lived processes).
pool_kwargs: dict = {"echo": False, "pool_pre_ping": True, "future": True}
db_url = (settings.DATABASE_URL or "").lower()
if "sqlite" in db_url or (settings.APP_ENV or "").lower() == "test":
    pool_kwargs["poolclass"] = NullPool

engine = create_async_engine(settings.DATABASE_URL, **pool_kwargs)
SessionLocal = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session
