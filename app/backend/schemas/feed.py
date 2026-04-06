from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.backend.schemas.coercion import coerce_json_string_list


class FeedItem(BaseModel):
    user_feed_id: int
    user_id: int
    ai_news_id: int
    raw_news_id: int | None = None
    target_persona: str | None = None
    final_title: str | None = None
    final_text: str | None = None
    image_urls: list[str] | None = None
    video_urls: list[str] | None = None
    category: str | None = None
    ai_score: float | None = None
    vector_status: str | None = None
    liked: bool | None = None
    saved: bool | None = None
    comment_count: int = 0
    created_at: datetime | None = None

    @field_validator("image_urls", "video_urls", mode="before")
    @classmethod
    def _coerce_url_lists(cls, v):
        return coerce_json_string_list(v)


class InteractionCreateRequest(BaseModel):
    user_id: int = Field(gt=0)
    ai_news_id: int = Field(gt=0)
    liked: bool | None = None
    viewed: bool | None = None
    watch_time: int | None = Field(default=None, ge=0)


class InteractionResponse(BaseModel):
    id: int
    status: str


class SavedToggleRequest(BaseModel):
    ai_news_id: int = Field(gt=0)


class SavedToggleResponse(BaseModel):
    ai_news_id: int
    saved: bool


class CommentCreateRequest(BaseModel):
    ai_news_id: int = Field(gt=0)
    parent_comment_id: int | None = Field(default=None, gt=0)
    content: str = Field(min_length=1, max_length=2000)


class CommentLikeToggleResponse(BaseModel):
    comment_id: int
    liked: bool
    like_count: int


class CommentItem(BaseModel):
    id: int
    ai_news_id: int
    user_id: int
    username: str
    parent_comment_id: int | None = None
    content: str
    like_count: int = 0
    liked_by_me: bool = False
    created_at: datetime | None = None
    replies: list[CommentItem] = Field(default_factory=list)
