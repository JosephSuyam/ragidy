from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, insert, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.documents import Chat, Message


async def insert_chat(db: AsyncSession, owner_id: UUID, title: str | None) -> Chat:
    """Insert a chat; flush only, the caller commits."""
    stmt = insert(Chat).values(owner_id=owner_id, title=title).returning(Chat)
    return (await db.scalars(stmt)).one()


async def list_chats(db: AsyncSession, owner_id: UUID) -> Sequence[Chat]:
    stmt = select(Chat).where(Chat.owner_id == owner_id).order_by(Chat.created_at.desc())
    return (await db.scalars(stmt)).all()


async def get_chat(db: AsyncSession, owner_id: UUID, chat_id: UUID) -> Chat | None:
    return await db.scalar(select(Chat).where(Chat.id == chat_id, Chat.owner_id == owner_id))


async def list_messages(db: AsyncSession, owner_id: UUID, chat_id: UUID) -> Sequence[Message]:
    """The chat's messages, oldest first; empty when the chat is missing or not the owner's."""
    stmt = (
        select(Message)
        .join(Chat, Chat.id == Message.chat_id)
        .where(Chat.id == chat_id, Chat.owner_id == owner_id)
        # created_at is the transaction start and each message commits on its own; id breaks ties.
        .order_by(Message.created_at, Message.id)
    )
    return (await db.scalars(stmt)).all()


async def insert_user_message(
    db: AsyncSession, owner_id: UUID, chat_id: UUID, content: str
) -> bool:
    """Insert a user message; flush only, the caller commits.

    Returns False, inserting nothing, when the chat is missing or not the owner's.
    """
    owned = (Chat.id == chat_id) & (Chat.owner_id == owner_id)
    return await _insert_message(db, owned, "user", content, [])


async def insert_assistant_message(
    db: AsyncSession, chat_id: UUID, content: str, citations: Sequence[dict[str, Any]]
) -> bool:
    """Insert an assistant message; flush only, the caller commits.

    Returns False, inserting nothing, when the chat is gone. UUID citation values become str.
    """
    # Owner-isolation exemption (ADR 0008): keyed by chat_id only, since a guest-to-user
    # migration may move the chat to another owner while the answer streams.
    json_safe = [
        {k: str(v) if isinstance(v, UUID) else v for k, v in citation.items()}
        for citation in citations
    ]
    return await _insert_message(db, Chat.id == chat_id, "assistant", content, json_safe)


async def _insert_message(
    db: AsyncSession,
    chat_filter: ColumnElement[bool],
    role: str,
    content: str,
    citations: list[dict[str, Any]],
) -> bool:
    """INSERT ... SELECT from the chats matching `chat_filter`, so a missing chat inserts no row."""
    source = select(Chat.id, literal(role), literal(content), literal(citations, JSONB)).where(
        chat_filter
    )
    stmt = (
        insert(Message)
        .from_select(["chat_id", "role", "content", "citations"], source)
        .returning(Message.id)
    )
    return await db.scalar(stmt) is not None
