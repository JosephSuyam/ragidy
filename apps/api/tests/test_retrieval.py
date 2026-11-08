import asyncio

import pytest
from llama_index.core import MockEmbedding

from app.rag.retrieval import embed_query


def test_embed_query_returns_the_mock_vector_for_the_query_text(
    mock_embeddings: list[MockEmbedding], monkeypatch: pytest.MonkeyPatch
) -> None:
    received: list[str] = []
    original = MockEmbedding.aget_query_embedding

    async def spy(self: MockEmbedding, query: str) -> list[float]:
        received.append(query)
        return await original(self, query)

    monkeypatch.setattr(MockEmbedding, "aget_query_embedding", spy)

    embedding = asyncio.run(embed_query("what is ragidy?"))

    assert len(embedding) == mock_embeddings[0].embed_dim
    assert all(isinstance(value, float) for value in embedding)
    assert received == ["what is ragidy?"]
