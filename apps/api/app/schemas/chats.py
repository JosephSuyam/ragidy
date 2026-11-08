from datetime import datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

TITLE_MAX_CHARS = 200
CONTENT_MAX_CHARS = 4000
# Postgres text rejects NUL, so refuse it here as a 422 instead of a 500 at INSERT.
NO_NUL = r"^[^\x00]*$"


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

    role: str
    content: str
    citations: list[CitationOut]
