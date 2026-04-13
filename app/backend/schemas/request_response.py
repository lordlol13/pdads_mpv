"""
Enhanced request/response validation schemas with strict typing and documentation.

These replace basic dict/Any types with proper Pydantic models for:
- Type safety
- Automatic validation
- OpenAPI documentation
- IDE autocompletion
"""

from typing import Optional, List, Dict, Any, Generic, TypeVar
from datetime import datetime
from pydantic import BaseModel, Field, validator, EmailStr, root_validator

T = TypeVar("T")


# =====================================================================
# Pagination
# =====================================================================

class PaginationParams(BaseModel):
    """Pagination parameters."""
    page: int = Field(default=1, ge=1, description="Page number (1-based)")
    page_size: int = Field(default=20, ge=1, le=100, description="Items per page")
    
    class Config:
        json_schema_extra = {"example": {"page": 1, "page_size": 20}}


class PaginatedResponse(BaseModel, Generic[T]):
    """Paginated response wrapper."""
    items: List[T]
    total: int
    page: int
    page_size: int
    has_more: bool = Field(description="Whether more items exist")


# =====================================================================
# Interest/User Profile
# =====================================================================

class InterestInput(BaseModel):
    """User interest input with strict validation."""
    
    topics: List[str] = Field(
        default=[],
        min_items=0,
        max_items=10,
        description="User interest topics (e.g., 'sports', 'technology')",
    )
    custom_topics: List[str] = Field(
        default=[],
        description="Custom user-defined topics",
    )
    profession: str = Field(
        default="",
        max_length=100,
        description="User profession/role",
    )
    
    @validator("topics", "custom_topics", pre=True, each_item=True)
    def normalize_topics(cls, v):
        """Normalize and validate topics."""
        if not isinstance(v, str):
            raise ValueError("Topic must be string")
        normalized = v.strip().lower()
        if not normalized:
            raise ValueError("Topic cannot be empty")
        if len(normalized) > 50:
            raise ValueError("Topic too long (max 50 chars)")
        return normalized
    
    class Config:
        json_schema_extra = {
            "example": {
                "topics": ["sports", "technology"],
                "custom_topics": ["esports"],
                "profession": "software engineer",
            }
        }


class UserProfile(BaseModel):
    """User profile response."""
    id: int
    username: str
    email: str
    interests: InterestInput
    location: Optional[str]
    country_code: Optional[str]
    created_at: datetime
    updated_at: datetime


# =====================================================================
# News Feed
# =====================================================================

class NewsArticle(BaseModel):
    """News article in feed."""
    
    id: int
    title: str
    final_text: str
    final_title: str
    category: str
    ai_score: float = Field(ge=0.0, le=10.0)
    source_url: Optional[str]
    image_url: Optional[str]
    published_at: datetime
    generation_score: Optional[float] = None
    
    class Config:
        json_schema_extra = {
            "example": {
                "id": 123,
                "title": "Breaking News",
                "final_text": "Article content...",
                "final_title": "Breaking: Important Update",
                "category": "sports",
                "ai_score": 8.5,
                "source_url": "https://example.com",
                "published_at": "2026-04-10T12:00:00Z",
            }
        }


class FeedInteraction(BaseModel):
    """User interaction with feed item."""
    
    interaction_type: str = Field(
        description="Type: 'like', 'view', 'share', 'save'",
        pattern="^(like|view|share|save)$"
    )
    ai_product_id: int
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class FeedResponse(BaseModel):
    """Paginated feed response."""
    items: List[NewsArticle]
    total: int
    page: int
    personalization: Dict[str, Any] = Field(
        description="Personalization metadata"
    )


# =====================================================================
# Authentication
# =====================================================================

class RegistrationStep1Input(BaseModel):
    """Registration step 1: email and password."""
    email: EmailStr
    password: str = Field(
        min_length=8,
        max_length=100,
        description="Password (min 8 chars, must include uppercase, lowercase, number)",
    )
    confirm_password: str
    
    @validator("password")
    def validate_password_strength(cls, v):
        """Validate password meets minimum requirements."""
        if not any(c.isupper() for c in v):
            raise ValueError("Password must include uppercase letter")
        if not any(c.islower() for c in v):
            raise ValueError("Password must include lowercase letter")
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must include digit")
        return v
    
    @validator("confirm_password")
    @root_validator(pre=False)
    def passwords_match(cls, values):
        """Ensure passwords match."""
        if values.get("password") != values.get("confirm_password"):
            raise ValueError("Passwords do not match")
        return values


class RegistrationStep2Input(BaseModel):
    """Registration step 2: interests."""
    interests: InterestInput


class RegistrationStep3Input(BaseModel):
    """Registration step 3: location and preferences."""
    username: str = Field(
        min_length=3,
        max_length=50,
        regex="^[a-zA-Z0-9_-]+$",
        description="Username (alphanumeric, underscore, hyphen)",
    )
    location: Optional[str] = Field(
        default=None,
        max_length=100,
        description="User location (city/region)",
    )
    country_code: Optional[str] = Field(
        default="UZ",
        max_length=2,
        regex="^[A-Z]{2}$",
        description="ISO 3166-1 alpha-2 country code",
    )


class LoginInput(BaseModel):
    """Login request."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Successful authentication response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token expiry time in seconds")
    user: UserProfile


# =====================================================================
# Pipeline/Admin
# =====================================================================

class PipelineJob(BaseModel):
    """Pipeline job details."""
    id: int
    raw_news_id: int
    status: str
    attempt_count: int
    error_message: Optional[str]
    created_at: datetime
    updated_at: datetime


class PipelineStats(BaseModel):
    """Pipeline statistics."""
    total_jobs: int
    pending: int
    processing: int
    completed: int
    failed: int
    success_rate: float


class BatchIngestionRequest(BaseModel):
    """Request to trigger batch ingestion."""
    personas: int = Field(
        default=5,
        ge=1,
        le=20,
        description="Number of persona segments to process",
    )
    batch_size: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Batch size for ingestion",
    )
