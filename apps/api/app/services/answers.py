from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import Answer
from app.agents.workflows import answer
from app.core.config import get_settings
from app.rag.retrieval import embed_query
from app.repositories.vector.chunks import search
from app.schemas.chunks import RetrievedChunk

TOP_K = 5


async def answer_question(db: AsyncSession, owner_id: UUID, question: str) -> Answer:
    """Answer from the owner's ready chunks embedded by the configured embed model (ADR 0007).

    Commits `db` at start and after each retrieval, so pending writes are committed and row
    locks (e.g. `lock_write_owner`) released; call it before any write or owner lock.
    """
    embed_model = get_settings().embed_model
    # Both commits end the read transaction so no pooled connection idles in it during
    # embedding or LLM calls (the auth dependency leaves one open).
    await db.commit()

    async def retrieve(query: str) -> list[RetrievedChunk]:
        chunks = await search(db, owner_id, embed_model, await embed_query(query), TOP_K)
        await db.commit()
        return chunks

    return await answer(question, retrieve)
