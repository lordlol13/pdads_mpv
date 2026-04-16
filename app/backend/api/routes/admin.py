from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.api.dependencies import get_db_session
from app.backend.core.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/delete-smoke-users")
async def delete_smoke_users(
    x_internal_api_key: str | None = Header(None),
    session: AsyncSession = Depends(get_db_session),
):
    # Protect this endpoint with INTERNAL_API_KEY to avoid accidental use.
    if not settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Internal API not configured")
    if x_internal_api_key != settings.INTERNAL_API_KEY:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid internal API key")

    # Count matching rows first for reporting.
    rv_count_res = await session.execute(
        text(
            "SELECT COUNT(1) FROM registration_verifications "
            "WHERE LOWER(email) LIKE 'onboarding+smoke%@resend.dev' OR LOWER(username) LIKE 'smoke_resend_%'"
        )
    )
    rv_count = int(rv_count_res.scalar() or 0)

    users_count_res = await session.execute(
        text(
            "SELECT COUNT(1) FROM users "
            "WHERE LOWER(email) LIKE 'onboarding+smoke%@resend.dev' OR LOWER(username) LIKE 'smoke_resend_%'"
        )
    )
    users_count = int(users_count_res.scalar() or 0)

    # Perform deletions.
    await session.execute(
        text(
            "DELETE FROM registration_verifications "
            "WHERE LOWER(email) LIKE 'onboarding+smoke%@resend.dev' OR LOWER(username) LIKE 'smoke_resend_%'"
        )
    )
    await session.execute(
        text(
            "DELETE FROM users "
            "WHERE LOWER(email) LIKE 'onboarding+smoke%@resend.dev' OR LOWER(username) LIKE 'smoke_resend_%'"
        )
    )
    await session.commit()

    return {
        "deleted_registration_verifications": rv_count,
        "deleted_users": users_count,
    }
