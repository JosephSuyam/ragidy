from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class EmbeddedChunk:
    """Plain data from app/rag ingestion to app/repositories/vector; position is the list index."""

    text: str
    embedding: list[float]
    metadata: dict[str, Any] = field(default_factory=dict)
