import asyncio
from typing import Any

from app.core import providers
from app.core.config import get_settings
from app.rag.chunking import chunk
from app.rag.errors import IngestionError
from app.rag.parsers import parse
from app.schemas.chunks import EmbeddedChunk


def _parse_and_chunk(data: bytes, mime: str, source: str) -> list[tuple[str, dict[str, Any]]]:
    return chunk(parse(data, mime, source))


async def ingest_document(data: bytes, mime: str, source: str) -> list[EmbeddedChunk]:
    """Parse, chunk and embed one document; IngestionError means the input itself is unusable.

    Embedding provider errors propagate unchanged, so the worker retries the whole document.
    """
    # shortcut: a timeout cannot stop this thread; parse in a killable subprocess if timeouts recur
    chunks = await asyncio.to_thread(_parse_and_chunk, data, mime, source)
    if not chunks:
        raise IngestionError("The document has no readable text.")
    embed_model = providers.get_embed_model(get_settings())
    embeddings = await embed_model.aget_text_embedding_batch([text for text, _ in chunks])
    return [
        EmbeddedChunk(text=text, embedding=embedding, metadata=metadata)
        for (text, metadata), embedding in zip(chunks, embeddings, strict=True)
    ]
