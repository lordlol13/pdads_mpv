from __future__ import annotations

from typing import Any, Iterable

from app.backend.db.session import SessionLocal
from app.backend.services.ingestion_service import create_raw_news


async def save_batch(articles: Iterable[dict[str, Any]], dry_run: bool = True) -> dict[str, Any]:
    """Save articles to DB using existing create_raw_news. If dry_run, don't persist, just report."""
    articles = list(articles)
    if dry_run:
        samples = []
        for a in articles[:10]:
            samples.append({"title": a.get("title"), "source_url": a.get("source_url")})
        return {"would_save": len(articles), "samples": samples}

    saved = 0
    errors = 0
    results = []

    async with SessionLocal() as session:
        for a in articles:
            payload = {
                "title": a.get("title") or "",
                "raw_text": a.get("content") or a.get("raw_text") or "",
                "image_url": a.get("image_url"),
                "source_url": a.get("source_url"),
                "category": a.get("category"),
                "region": a.get("region"),
                "is_urgent": a.get("is_urgent", False),
            }
            try:
                row = await create_raw_news(session, payload)
                results.append(row)
                saved += 1
            except Exception as exc:  # pragma: no cover - bubble up in real runs
                errors += 1

    return {"saved": saved, "errors": errors, "samples": results[:5]}
