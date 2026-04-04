from datetime import datetime
from pydantic import BaseModel


class EnqueueResponse(BaseModel):
    task_id: str
    raw_news_id: int
    status: str  # queued


class TaskStatusResponse(BaseModel):
    task_id: str
    state: str   # PENDING/STARTED/SUCCESS/FAILURE
    result: dict | None = None


class RawNewsItem(BaseModel):
    id: int
    title: str
    source_url: str | None
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
    category: str | None
    ai_score: float | None
    vector_status: str | None
    created_at: datetime | None