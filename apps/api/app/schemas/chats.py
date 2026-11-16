from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.schemas.common import NO_NUL

TITLE_MAX_CHARS = 200
CONTENT_MAX_CHARS = 4000


class ChatCreate(BaseModel):
    title: str | None = Field(default=None, max_length=TITLE_MAX_CHARS, pattern=NO_NUL)


class ChatOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str | None
    created_at: datetime


class MessageIn(BaseModel):
    content: Annotated[
        str,
        StringConstraints(
            strip_whitespace=True, min_length=1, max_length=CONTENT_MAX_CHARS, pattern=NO_NUL
        ),
    ]


class CitationOut(BaseModel):
    document_id: UUID
    source: str
    page: int | None
    snippet: str


class MessageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    role: Literal["user", "assistant"]
    content: str
    citations: list[CitationOut]
