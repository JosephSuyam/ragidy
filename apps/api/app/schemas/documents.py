from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class UrlIn(BaseModel):
    # Plain str: fetch_url rejects non-http(s) URLs with 422 url_blocked.
    url: str = Field(max_length=2048)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str
    status: str
    error: str | None
    attempts: int
    created_at: datetime
