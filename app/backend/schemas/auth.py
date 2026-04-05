from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class AuthRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    location: str | None = None
    interests: dict[str, Any] | None = None
    country_code: str | None = None
    region_code: str | None = None


class AuthLoginRequest(BaseModel):
    identifier: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_minutes: int


class UserPublic(BaseModel):
    id: int
    username: str
    email: str | None = None
    location: str | None = None
    interests: dict[str, Any] | None = None
    is_active: bool | None = None
    is_verified: bool | None = None
    country_code: str | None = None
    region_code: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
