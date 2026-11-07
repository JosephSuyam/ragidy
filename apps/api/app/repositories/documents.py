from uuid import UUID

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.documents import Document


async def count_documents(db: AsyncSession, owner_id: UUID) -> int:
    stmt = select(func.count()).select_from(Document).where(Document.owner_id == owner_id)
    return (await db.execute(stmt)).scalar_one()


async def insert_document(
    db: AsyncSession, id: UUID, owner_id: UUID, source: str, embed_model: str
) -> Document:
    """Insert a pending document; flush only, the caller commits.

    The caller picks `id` because the object key documents/<id> is written first (ADR 0002).
    """
    stmt = (
        insert(Document)
        .values(id=id, owner_id=owner_id, source=source, embed_model=embed_model)
        .returning(Document)
    )
    return (await db.scalars(stmt)).one()
