from datetime import datetime

from pydantic import BaseModel, field_validator

from app.backend.schemas.coercion import coerce_json_string_list


class EnqueueResponse(BaseModel):
    task_id: str
    raw_news_id: int
    status: str


class TaskStatusResponse(BaseModel):
    task_id: str
    state: str
    result: dict[str, object] | None = None


class RawNewsItem(BaseModel):
    id: int
    title: str
    source_url: str | None
    image_url: str | None
    raw_text: str | None
    category: str | None
    region: str | None
    is_urgent: bool | None
    process_status: str | None
    error_message: str | None
    attempt_count: int | None
    created_at: datetime | None


class AiNewsItem(BaseModel):
    id: int
    raw_news_id: int
    target_persona: str
    final_title: str
    final_text: str
    image_urls: list[str] | None = None
    video_urls: list[str] | None = None
    category: str | None
    ai_score: float | None
    vector_status: str | None
    created_at: datetime | None

    @field_validator("image_urls", "video_urls", mode="before")
    @classmethod
    def _coerce_url_lists(cls, v):
        return coerce_json_string_list(v)