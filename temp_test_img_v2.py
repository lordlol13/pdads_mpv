import asyncio
import json
import re

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text
import httpx

from app.backend.services.media_service import _normalize_candidate_url


async def main():
    url = (
        "postgresql+asyncpg://postgres:kcIOcotagFNWoQfnysHiWtDpEffCUvVz@maglev.proxy.rlwy.net:10621/railway"
    )
    engine = create_async_engine(url, future=True)
    async with engine.connect() as conn:
        result = await conn.execute(
            text(
                "SELECT id, image_urls FROM ai_news WHERE image_urls IS NOT NULL ORDER BY created_at DESC LIMIT 1"
            )
        )
        row = result.mappings().first()
        if not row:
            print("no row")
            await engine.dispose()
            return

        img_field = row.get("image_urls")

        imgs = []
        if not img_field:
            imgs = []
        elif isinstance(img_field, str):
            # Try JSON (JSON string stored), then fall back to extracting http(s) URLs
            try:
                parsed = json.loads(img_field)
                if isinstance(parsed, str):
                    imgs = [parsed]
                elif isinstance(parsed, (list, tuple)):
                    imgs = list(parsed)
                else:
                    imgs = [str(parsed)]
            except Exception:
                # Handle Postgres array-like string: {https://...,https://...}
                found = re.findall(r"https?://[^\s,}\]]+", img_field)
                if found:
                    imgs = found
                else:
                    s = img_field.strip()
                    if s.startswith("{") and s.endswith("}"):
                        inner = s[1:-1]
                        parts = [p.strip().strip('"') for p in inner.split(",") if p.strip()]
                        imgs = parts
                    else:
                        imgs = [s]
        elif isinstance(img_field, (list, tuple)):
            imgs = list(img_field)
        else:
            try:
                imgs = list(img_field)
            except Exception:
                imgs = [str(img_field)]

        img = imgs[0] if imgs else None
        print(f"ai_news id={row.get('id')} img_found={bool(img)} img={img}")
        if not img:
            await engine.dispose()
            return

        # Normalize before fetching (ensure scheme etc.)
        try:
            normalized = _normalize_candidate_url(img)
            if normalized:
                img = normalized
        except Exception:
            pass

        async with httpx.AsyncClient(follow_redirects=True, timeout=15) as client:
            headers_list = [
                {
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
                    "Referer": "https://pdadsmpv-production.up.railway.app/",
                },
                {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"},
                {"User-Agent": "python-httpx/0.24.0"},
            ]
            for hdrs in headers_list:
                try:
                    resp = await client.get(img, headers=hdrs)
                    ct = resp.headers.get("content-type")
                    print(f"hdrs Referer={'Referer' in hdrs} status={resp.status_code} content-type={ct} len={len(resp.content)}")
                except Exception as e:
                    print(f"hdrs Referer={'Referer' in hdrs} error={repr(e)}")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
