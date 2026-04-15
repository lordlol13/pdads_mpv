import asyncio
import logging
from app.backend.db.session import engine, Base

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        logger.info("✅ Все таблицы созданы успешно!")


asyncio.run(create_tables())
