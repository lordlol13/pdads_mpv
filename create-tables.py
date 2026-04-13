import asyncio
from app.backend.db.session import engine, Base

async def create_tables():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        print("✅ Все таблицы созданы успешно!")

asyncio.run(create_tables())
