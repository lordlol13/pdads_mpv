from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.api.dependencies import get_db_session, get_current_user
from app.backend.models.user_event import UserEvent

router = APIRouter()

VALID_EVENTS = {"view", "like", "skip", "long_view"}


@router.post("/event")
async def track_event(
    article_id: int,
    event_type: str,
    dwell_time: float = 0.0,
    current_user: dict = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Record a simple user event. Requires authentication.

    Minimal validation is performed to avoid junk event types.
    """
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")

    if event_type not in VALID_EVENTS:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="invalid_event")

    user_id = int(current_user.get("id"))

    event = UserEvent(
        user_id=user_id,
        article_id=article_id,
        event_type=event_type,
        dwell_time=float(dwell_time or 0.0),
    )

    try:
        session.add(event)
        await session.commit()
    except Exception:
        # Don't expose DB internals; return generic error
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="cannot_record_event")

    return {"status": "ok"}
