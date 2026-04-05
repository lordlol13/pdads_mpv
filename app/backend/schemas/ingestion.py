from datetime import datetime

from pydantic import BaseModel, Field


class RawNewsCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    source_url: str | None = None
    raw_text: str | None = None
    category: str | None = None
    region: str | None = None
    is_urgent: bool | None = False


class RawNewsCreateResponse(BaseModel):
    id: int
    content_hash: str
    process_status: str | None = None
    created_at: datetime | None = None
