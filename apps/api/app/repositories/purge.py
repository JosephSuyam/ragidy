"""Guest purge queries (R14).

Worker-only and not owner-filtered: only app/workers calls it. Flush only, the caller commits.
Lock the owner with `owners.lock_owner` first, and finish with `owners.delete_owner`.
"""

from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import Guest, Session
from app.models.documents import Chat, Document


async def expired_guest_owner_ids(db: AsyncSession, limit: int) -> list[UUID]:
    stmt = (
        select(Guest.owner_id)
        .where(Guest.expires_at <= func.now())
        .order_by(Guest.expires_at)
        .limit(limit)
    )
    return list((await db.scalars(stmt)).all())


async def guest_expired(db: AsyncSession, owner_id: UUID) -> bool:
    """False when the guest is gone (deleted or migrated to a user) or still live."""
    stmt = select(Guest.id).where(Guest.owner_id == owner_id, Guest.expires_at <= func.now())
    return await db.scalar(stmt) is not None


async def owner_document_ids(db: AsyncSession, owner_id: UUID) -> list[UUID]:
    stmt = select(Document.id).where(Document.owner_id == owner_id)
    return list((await db.scalars(stmt)).all())


async def delete_owned_rows(db: AsyncSession, owner_id: UUID) -> None:
    """Delete the owner's documents (chunks cascade), then chats (messages cascade)."""
    await db.execute(delete(Document).where(Document.owner_id == owner_id))
    await db.execute(delete(Chat).where(Chat.owner_id == owner_id))


async def delete_expired_sessions(db: AsyncSession) -> int:
    stmt = delete(Session).where(Session.expires_at <= func.now())
    # AsyncSession.execute is typed as Result, but a DML statement returns a CursorResult.
    return cast(CursorResult[Any], await db.execute(stmt)).rowcount
