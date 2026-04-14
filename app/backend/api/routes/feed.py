from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.api.dependencies import get_current_user, get_db_session
from app.backend.schemas.feed import (
    CommentCreateRequest,
    CommentItem,
    CommentLikeToggleResponse,
    FeedItem,
    InteractionCreateRequest,
    InteractionResponse,
    SavedToggleRequest,
    SavedToggleResponse,
)
from app.backend.services.feed_service import (
    create_comment,
    get_comments_tree,
    get_user_feed,
    record_interaction as record_user_interaction,
    toggle_comment_like,
    toggle_saved_news,
)

from app.backend.core.logging import ContextLogger

logger = ContextLogger(__name__)

router = APIRouter(prefix="/feed", tags=["feed"])


def _current_user_id(current_user: dict) -> int:
    return int(current_user["id"])


@router.get("/me", response_model=list[FeedItem])
async def my_feed(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    try:
        user_id = _current_user_id(current_user)
        items = await get_user_feed(session, user_id, limit)
        return [FeedItem(**item) for item in items]
    except Exception as exc:
        correlation_id = getattr(request.state, "correlation_id", None)
        logger.exception("GET /api/feed/me crashed", correlation_id=correlation_id, exception_type=exc.__class__.__name__)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error") from exc


@router.get("/search", response_model=list[FeedItem])
async def search_feed(
    q: str = Query(min_length=1, max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = _current_user_id(current_user)
    items = await get_user_feed(session, user_id, max(limit * 4, 100))

    query = q.strip().lower()
    if not query:
        return [FeedItem(**item) for item in items[:limit]]

    filtered: list[dict] = []
    for item in items:
        haystack = " ".join(
            str(value or "")
            for value in (
                item.get("final_title"),
                item.get("final_text"),
                item.get("target_persona"),
                item.get("category"),
                item.get("raw_news_id"),
            )
        ).lower()
        if query in haystack:
            filtered.append(item)

    return [FeedItem(**item) for item in filtered[:limit]]


@router.post("/interactions", response_model=InteractionResponse)
async def create_interaction(
    payload: InteractionCreateRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = _current_user_id(current_user)
    if payload.user_id != user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot create interaction for another user",
        )

    record = await record_user_interaction(session, payload.model_dump())
    return InteractionResponse(id=record["id"], status="created")


@router.post("/saved/toggle", response_model=SavedToggleResponse)
async def toggle_saved_item(
    payload: SavedToggleRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = _current_user_id(current_user)
    saved = await toggle_saved_news(session, user_id, payload.ai_news_id)
    return SavedToggleResponse(ai_news_id=payload.ai_news_id, saved=saved)


@router.get("/comments/{ai_news_id}", response_model=list[CommentItem])
async def list_comments(
    ai_news_id: int,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = _current_user_id(current_user)
    if ai_news_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ai_news_id must be > 0")

    rows = await get_comments_tree(session, user_id=user_id, ai_news_id=ai_news_id)
    return [CommentItem(**row) for row in rows]


@router.post("/comments", response_model=CommentItem)
async def add_comment(
    payload: CommentCreateRequest,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = _current_user_id(current_user)
    try:
        row = await create_comment(
            session,
            user_id=user_id,
            ai_news_id=payload.ai_news_id,
            parent_comment_id=payload.parent_comment_id,
            content=payload.content,
        )
    except ValueError as exc:
        detail = str(exc)
        if detail in {"ai_news_not_found", "parent_comment_not_found"}:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail) from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail) from exc

    return CommentItem(**row)


@router.post("/comments/{comment_id}/like-toggle", response_model=CommentLikeToggleResponse)
async def toggle_comment_like_route(
    comment_id: int,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    user_id = _current_user_id(current_user)
    if comment_id <= 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="comment_id must be > 0")

    try:
        result = await toggle_comment_like(session, user_id=user_id, comment_id=comment_id)
    except ValueError as exc:
        if str(exc) == "comment_not_found":
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="comment_not_found") from exc
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return CommentLikeToggleResponse(**result)
