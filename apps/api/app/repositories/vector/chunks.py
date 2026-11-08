from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.documents import Chunk
from app.schemas.chunks import EmbeddedChunk


async def replace_chunks(
    db: AsyncSession, document_id: UUID, chunks: Sequence[EmbeddedChunk]
) -> int:
    """Delete the document's chunks, then insert `chunks`; flush only, the caller commits.

    Deleting first keeps a retry after a partial run from leaving duplicates (ADR 0002).
    """
    await db.execute(delete(Chunk).where(Chunk.document_id == document_id))
    if chunks:
        rows = [
            {
                "document_id": document_id,
                "position": position,
                "text": chunk.text,
                "metadata_": chunk.metadata,
                "embedding": chunk.embedding,
            }
            for position, chunk in enumerate(chunks)
        ]
        await db.execute(insert(Chunk), rows)
    return len(chunks)
