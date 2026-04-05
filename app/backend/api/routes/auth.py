from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.api.dependencies import get_current_user, get_db_session
from app.backend.core.config import settings
from app.backend.schemas.auth import (
    AuthLoginRequest,
    AuthRegisterRequest,
    TokenResponse,
    UserPublic,
)
from app.backend.services.auth_service import (
    authenticate_user,
    issue_access_token,
    register_user,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserPublic)
async def register(payload: AuthRegisterRequest, session: AsyncSession = Depends(get_db_session)):
    user = await register_user(
        session,
        username=payload.username,
        email=payload.email,
        password=payload.password,
        location=payload.location,
        interests=payload.interests,
        country_code=payload.country_code,
        region_code=payload.region_code,
    )
    return UserPublic(**user)


@router.post("/login", response_model=TokenResponse)
async def login(payload: AuthLoginRequest, session: AsyncSession = Depends(get_db_session)):
    user = await authenticate_user(session, payload.identifier, payload.password)
    token = issue_access_token(user)
    return TokenResponse(access_token=token, expires_in_minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES)


@router.get("/me", response_model=UserPublic)
async def me(current_user: dict = Depends(get_current_user)):
    return UserPublic(**current_user)
