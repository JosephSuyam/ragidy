from collections.abc import Sequence
from uuid import UUID

from sqlalchemy import func, insert, select, update
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


async def list_documents(db: AsyncSession, owner_id: UUID) -> Sequence[Document]:
    stmt = (
        select(Document).where(Document.owner_id == owner_id).order_by(Document.created_at.desc())
    )
    return (await db.scalars(stmt)).all()


async def get_document(db: AsyncSession, owner_id: UUID, id: UUID) -> Document | None:
    return await db.scalar(select(Document).where(Document.id == id, Document.owner_id == owner_id))


async def requeue_for_owner(db: AsyncSession, owner_id: UUID, id: UUID) -> Document | None:
    """Queue a failed or ready document again (ADR 0002); flush only, the caller commits.

    Returns None when the document is missing, not the owner's, or pending or processing.
    """
    stmt = (
        update(Document)
        .where(
            Document.id == id,
            Document.owner_id == owner_id,
            Document.status.in_(("failed", "ready")),
        )
        .values(status="pending", attempts=0, run_after=func.now(), error=None)
        .returning(Document)
    )
    return await db.scalar(stmt)
