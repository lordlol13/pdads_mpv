from datetime import datetime
from pydantic import BaseModel, Field


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
    created_at: datetime | None = None


class InteractionCreateRequest(BaseModel):
    user_id: int = Field(gt=0)
    ai_news_id: int = Field(gt=0)
    liked: bool | None = None
    viewed: bool | None = None
    watch_time: int | None = Field(default=None, ge=0)


class InteractionResponse(BaseModel):
    id: int
    status: str
