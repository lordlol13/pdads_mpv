import json
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.backend.core.config import settings
from app.backend.core.security import create_access_token, hash_password, verify_password


async def get_user_by_identifier(session: AsyncSession, identifier: str) -> dict[str, Any] | None:
    query = """
    SELECT
        id, username, email, location, interests, is_active, is_verified,
        country_code, region_code, created_at, updated_at, password_hash
    FROM users
    WHERE username = :identifier OR email = :identifier
    ORDER BY id
    LIMIT 1
    """
    result = await session.execute(text(query), {"identifier": identifier})
    row = result.mappings().first()
    return dict(row) if row else None


async def get_user_by_id(session: AsyncSession, user_id: int) -> dict[str, Any] | None:
    query = """
    SELECT
        id, username, email, location, interests, is_active, is_verified,
        country_code, region_code, created_at, updated_at
    FROM users
    WHERE id = :user_id
    LIMIT 1
    """
    result = await session.execute(text(query), {"user_id": user_id})
    row = result.mappings().first()
    return dict(row) if row else None


async def register_user(
    session: AsyncSession,
    *,
    username: str,
    email: str,
    password: str,
    location: str | None = None,
    interests: dict[str, Any] | None = None,
    country_code: str | None = None,
    region_code: str | None = None,
) -> dict[str, Any]:
    existing = await get_user_by_identifier(session, username)
    if existing is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already exists")

    existing_email = await get_user_by_identifier(session, email)
    if existing_email is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already exists")

    password_hash = hash_password(password)
    interests_json = json.dumps(interests or {})

    query = """
    INSERT INTO users (
        username, location, interests, created_at, email, password_hash,
        is_active, is_verified, country_code, region_code, updated_at
    )
    VALUES (
        :username, :location, CAST(:interests AS jsonb), NOW(), :email, :password_hash,
        TRUE, FALSE, :country_code, :region_code, NOW()
    )
    RETURNING
        id, username, email, location, interests, is_active, is_verified,
        country_code, region_code, created_at, updated_at
    """
    result = await session.execute(
        text(query),
        {
            "username": username,
            "location": location,
            "interests": interests_json,
            "email": email,
            "password_hash": password_hash,
            "country_code": country_code,
            "region_code": region_code,
        },
    )
    await session.commit()
    row = result.mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to create user")
    return dict(row)


async def authenticate_user(session: AsyncSession, identifier: str, password: str) -> dict[str, Any]:
    user = await get_user_by_identifier(session, identifier)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if not user.get("password_hash") or not verify_password(password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    if user.get("is_active") is False:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is inactive")

    return user


def issue_access_token(user: dict[str, Any]) -> str:
    return create_access_token(
        {"sub": str(user["id"]), "username": user.get("username")},
        secret_key=settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
        expires_minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES,
    )
