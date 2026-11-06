from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.documents import Document


async def count_documents(db: AsyncSession, owner_id: UUID) -> int:
    stmt = select(func.count()).select_from(Document).where(Document.owner_id == owner_id)
    return (await db.execute(stmt)).scalar_one()
