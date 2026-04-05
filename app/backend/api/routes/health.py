import asyncio

import redis.asyncio as redis
from fastapi import APIRouter
from sqlalchemy import text

from app.backend.core.celery_app import celery_app
from app.backend.core.config import settings
from app.backend.db.session import SessionLocal

router = APIRouter(tags=["health"])


@router.get("/health")
def health_check():
    return {"status": "ok"}


@router.get("/health/dependencies")
async def health_dependencies_check():
    db_ok = False
    redis_ok = False
    celery_ok = False
    details: dict[str, str] = {}

    try:
        async with SessionLocal() as session:
            result = await session.execute(text("SELECT 1"))
            db_ok = result.scalar_one() == 1
    except Exception as exc:
        details["database"] = str(exc)

    try:
        redis_client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        redis_ok = bool(await redis_client.ping())
        await redis_client.aclose()
    except Exception as exc:
        details["redis"] = str(exc)

    try:
        inspect = celery_app.control.inspect(timeout=1.0)
        ping_result = await asyncio.to_thread(inspect.ping)
        celery_ok = bool(ping_result)
        if not celery_ok:
            details["celery"] = "No Celery workers responded to ping"
    except Exception as exc:
        details["celery"] = str(exc)

    dependencies = {
        "database": "up" if db_ok else "down",
        "redis": "up" if redis_ok else "down",
        "celery_worker": "up" if celery_ok else "down",
    }

    overall = "ok" if all([db_ok, redis_ok, celery_ok]) else "degraded"
    payload = {"status": overall, "dependencies": dependencies}
    if details:
        payload["details"] = details
    return payload
