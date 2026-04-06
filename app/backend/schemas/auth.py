from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class AuthRegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    location: str | None = None
    interests: dict[str, Any] | None = None
    country_code: str | None = None
    region_code: str | None = None


class AuthCheckAvailabilityRequest(BaseModel):
    username: str | None = Field(default=None, min_length=3, max_length=100)
    email: str | None = Field(default=None, min_length=5, max_length=255)

    @model_validator(mode="after")
    def _validate_any_field(self) -> "AuthCheckAvailabilityRequest":
        if not (self.username or self.email):
            raise ValueError("username or email is required")
        return self


class AuthCheckAvailabilityResponse(BaseModel):
    username_exists: bool | None = None
    email_exists: bool | None = None


class AuthRegisterStartRequest(BaseModel):
    username: str = Field(min_length=3, max_length=100)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class AuthRegisterStartResponse(BaseModel):
    verification_id: str
    expires_in_seconds: int
    debug_code: str | None = None


class AuthVerifyCodeRequest(BaseModel):
    verification_id: str = Field(min_length=8, max_length=128)
    code: str = Field(min_length=4, max_length=16)


class AuthVerifyCodeResponse(BaseModel):
    verification_id: str
    verified: bool


class AuthRegisterCompleteRequest(BaseModel):
    verification_id: str = Field(min_length=8, max_length=128)
    interests: list[str] = Field(default_factory=list)
    custom_interests: list[str] = Field(default_factory=list)
    profession: str | None = None
    country_code: str | None = None
    country_name: str | None = None
    city: str | None = None
    region_code: str | None = None

    @model_validator(mode="after")
    def _validate_interests(self) -> "AuthRegisterCompleteRequest":
        cleaned = [item.strip() for item in self.interests if item and item.strip()]
        custom_cleaned = [item.strip() for item in self.custom_interests if item and item.strip()]
        if not cleaned and not custom_cleaned:
            raise ValueError("At least one interest is required")
        if not (self.country_code and self.country_code.strip()):
            raise ValueError("Country is required")
        if not (self.city and self.city.strip()):
            raise ValueError("City is required")
        self.interests = cleaned
        self.custom_interests = custom_cleaned
        self.country_code = self.country_code.strip().upper()
        self.city = self.city.strip()
        return self


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
