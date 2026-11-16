from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import NO_NUL


class UrlIn(BaseModel):
    # Plain str: fetch_url rejects non-http(s) URLs with 422 url_blocked.
    url: str = Field(max_length=2048, pattern=NO_NUL)


class DocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source: str
    status: Literal["pending", "processing", "ready", "failed"]
    error: str | None
    attempts: int
    created_at: datetime
