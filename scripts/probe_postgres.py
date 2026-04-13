import asyncio
import asyncpg

candidates = [
    "postgresql://postgres:postgres@localhost:5432/news_mvp",
    "postgresql://postgres@localhost:5432/news_mvp",
    "postgresql://postgres:admin@localhost:5432/news_mvp",
    "postgresql://Home@localhost:5432/news_mvp",
    "postgresql://Home:postgres@localhost:5432/news_mvp",
    "postgresql://localhost:5432/news_mvp",
]

async def test(url):
    try:
        conn = await asyncpg.connect(url, timeout=3)
        await conn.execute("select 1")
        await conn.close()
        return True, None
    except Exception as e:
        return False, str(e)

async def main():
    for url in candidates:
        ok, err = await test(url)
        if ok:
            print("OK", url)
            return
        else:
            print("FAIL", url, "=>", err[:120])

asyncio.run(main())
