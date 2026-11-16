from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import NotRequired, TypedDict
from uuid import UUID

from app.schemas.chunks import RetrievedChunk

Retrieve = Callable[[str], Awaitable[list[RetrievedChunk]]]


@dataclass(frozen=True, slots=True)
class AnswerContext:
    """Run-scoped LangGraph context; never checkpointed, so retrieve stays out of state."""

    retrieve: Retrieve


class Citation(TypedDict):
    document_id: UUID
    source: str
    page: int | None
    snippet: str


class Answer(TypedDict):
    answer: str
    citations: list[Citation]


class CorrectiveRagState(TypedDict):
    question: str
    query: str
    rewrites: int
    chunks: NotRequired[list[RetrievedChunk]]
    repeated: NotRequired[bool]
    kept: NotRequired[list[RetrievedChunk]]
    answer: NotRequired[str]
    citations: NotRequired[list[Citation]]
