from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """Plain data from app/rag ingestion to app/repositories/vector; position is the list index."""

    text: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class RetrievedChunk:
    """Plain data from app/repositories/vector search to app/rag and app/agents (ADR 0007).

    metadata holds document_id, source (what a citation shows) and page.
    """

    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)
