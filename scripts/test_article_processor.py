import asyncio
import os
from app.backend.services.article_processor import process_article


async def fetch_from_file(session, url: str):
    # support file:// paths for quick local tests
    if url.startswith("file://"):
        path = url[7:]
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    # fallback to simple httpx fetch
    try:
        import httpx
        async with httpx.AsyncClient() as client:
            r = await client.get(url, timeout=15.0)
            r.raise_for_status()
            return r.text
    except Exception:
        return None


async def main():
    sample = "scripts/_daryo_sample.html"
    url = f"file://{sample}"
    res = await process_article(None, url, fetch_from_file)
    print("--- result ---")
    print(res)


if __name__ == "__main__":
    asyncio.run(main())
