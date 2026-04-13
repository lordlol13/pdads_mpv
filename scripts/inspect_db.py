import asyncio
from app.backend.core.config import settings
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

async def main():
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.begin() as conn:
        users = await conn.execute(text('select id, email, username, password_hash, created_at from users order by created_at desc limit 10'))
        print('recent users:')
        for r in users.mappings().all():
            print(r)
        regs = await conn.execute(text('select id, username, email, is_verified, consumed_at, created_at from registration_verifications order by created_at desc limit 10'))
        print('\nrecent regs:')
        for r in regs.mappings().all():
            print(r)
    await engine.dispose()

if __name__ == '__main__':
    asyncio.run(main())
