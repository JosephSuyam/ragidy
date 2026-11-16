from uuid import UUID

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import Owner
from app.models.documents import Chat, Document


async def lock_owner(db: AsyncSession, owner_id: UUID) -> bool:
    stmt = select(Owner.id).where(Owner.id == owner_id).with_for_update()
    return await db.scalar(stmt) is not None


async def transfer_owned_rows(db: AsyncSession, from_owner: UUID, to_owner: UUID) -> None:
    for model in (Document, Chat):
        await db.execute(
            update(model).where(model.owner_id == from_owner).values(owner_id=to_owner)
        )


async def delete_owner(db: AsyncSession, owner_id: UUID) -> None:
    """Delete an owner; its guest or user row cascades. Move its documents and chats first."""
    await db.execute(delete(Owner).where(Owner.id == owner_id))
