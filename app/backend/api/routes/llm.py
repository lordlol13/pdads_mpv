from typing import Optional

from fastapi import APIRouter, Header, HTTPException, status
from pydantic import BaseModel

from app.backend.core.config import settings
from app.backend.services.llm_service import generate_news
from app.backend.services.resilience_service import check_rate_limit, _llm_limiter

router = APIRouter(prefix="/llm", tags=["llm"])


class GenerateArticleRequest(BaseModel):
    title: str
    raw_text: str
    category: Optional[str] = "general"
    target_persona: Optional[str] = "general"
    region: Optional[str] = None
    profession: Optional[str] = None
    user_geo: Optional[str] = None
    rewrite_round: Optional[int] = 1


@router.post("/generate_article")
async def generate_article(payload: GenerateArticleRequest, x_internal_api_key: Optional[str] = Header(None)):
    # Protect production: require INTERNAL_API_KEY to be set and provided.
    if settings.INTERNAL_API_KEY:
        if x_internal_api_key != settings.INTERNAL_API_KEY:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")
    else:
        # If in production and key is not set, disable this endpoint to avoid accidental heavy LLM usage.
        if (settings.APP_ENV or "").lower() in ("prod", "production", "stage", "staging"):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Internal generation disabled in production until INTERNAL_API_KEY is configured",
            )

    # Basic rate limiting to avoid spikes
    allowed = await check_rate_limit(
        f"api:generate_article:{payload.target_persona}", limiter=_llm_limiter, limit=settings.LLM_RATE_LIMIT_PER_MINUTE, window_seconds=60
    )
    if not allowed:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Rate limit exceeded")

    result = await generate_news(
        raw_text=payload.raw_text,
        title=payload.title,
        category=payload.category,
        target_persona=payload.target_persona,
        region=payload.region,
        profession=payload.profession,
        user_geo=payload.user_geo,
        rewrite_round=payload.rewrite_round,
    )

    if result is None:
        return {
            "final_title": payload.title,
            "final_text": payload.raw_text[:500] if payload.raw_text else "",
            "ai_score": 0.0,
        }

    return result
