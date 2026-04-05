from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.api.dependencies import get_current_user, get_db_session
from app.backend.schemas.feed import FeedItem, InteractionCreateRequest, InteractionResponse
from app.backend.services.feed_service import get_user_feed, record_interaction as record_user_interaction

router = APIRouter(prefix="/feed", tags=["feed"])


@router.get("/me", response_model=list[FeedItem])
async def my_feed(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    items = await get_user_feed(session, current_user["id"], limit)
    return [FeedItem(**item) for item in items]


@router.post("/interactions", response_model=InteractionResponse)
async def create_interaction(
    payload: InteractionCreateRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    if payload.user_id != current_user["id"]:
        raise HTTPException(status_code=403, detail="Cannot create interaction for another user")

    record = await record_user_interaction(session, payload.model_dump())
    return InteractionResponse(id=record["id"], status="created")
