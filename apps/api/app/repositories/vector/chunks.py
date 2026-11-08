from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.documents import Chunk, Document
from app.schemas.chunks import EmbeddedChunk, RetrievedChunk


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


async def search(
    db: AsyncSession,
    owner_id: UUID,
    embed_model: str,
    query_embedding: Sequence[float],
    k: int,
) -> list[RetrievedChunk]:
    """The owner's `k` ready chunks closest to `query_embedding` by cosine, best first; read-only.

    Only chunks embedded by `embed_model` with the query's dimension are compared, because the
    column has no fixed dimension and pgvector raises on mixed-dimension distances (ADR 0006).
    """
    distance = Chunk.embedding.cosine_distance(query_embedding).label("distance")
    rows = await db.execute(
        select(Chunk.text, Chunk.metadata_, Chunk.document_id, Document.source, distance)
        .join(Document, Document.id == Chunk.document_id)
        .where(
            Document.owner_id == owner_id,
            Document.status == "ready",
            Document.embed_model == embed_model,
            func.vector_dims(Chunk.embedding) == len(query_embedding),
        )
        .order_by(distance)
        .limit(k)
    )
    return [
        RetrievedChunk(
            text=row.text,
            score=1 - row.distance,
            metadata={
                "document_id": row.document_id,
                "source": row.source,
                "page": row.metadata_.get("page"),
            },
        )
        for row in rows
    ]
