import asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from app.backend.core.config import settings


async def main() -> None:
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as conn:
        result = await conn.execute(text("select count(*) from users"))
        print("DATABASE_URL=", settings.DATABASE_URL)
        print("users_count=", result.scalar())
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
