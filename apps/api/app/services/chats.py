import logging
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any, Literal
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import Answer
from app.core.config import get_settings
from app.core.errors import AppError
from app.models.documents import Chat, Message
from app.repositories.chats import (
    delete_chat,
    get_chat,
    insert_assistant_message,
    insert_chat,
    insert_user_message,
    list_chats,
    list_messages,
)
from app.services.answers import stream_answer_question
from app.services.owners import CurrentOwner, lock_write_owner
from app.services.rate_limit import chat_messages, rate_limited

logger = logging.getLogger(__name__)

ANSWER_FAILED = "The answer could not be generated; try again later"

ChatEvent = tuple[Literal["token", "citations", "done", "error"], Any]
ANSWER_FAILED_EVENT: ChatEvent = ("error", {"code": "answer_failed", "detail": ANSWER_FAILED})


@dataclass(frozen=True)
class PostedMessage:
    owner_id: UUID
    chat_id: UUID
    content: str


async def create_chat(db: AsyncSession, owner: CurrentOwner, title: str | None) -> Chat:
    """Lock the owner row, insert the chat and commit; 401 when the owner was deleted."""
    await lock_write_owner(db, owner)
    chat = await insert_chat(db, owner.owner_id, title)
    await db.commit()
    return chat


async def list_owner_chats(db: AsyncSession, owner: CurrentOwner | None) -> Sequence[Chat]:
    """The owner's chats, newest first; none without an owner."""
    return [] if owner is None else await list_chats(db, owner.owner_id)


async def list_chat_messages(
    db: AsyncSession, owner: CurrentOwner | None, chat_id: UUID
) -> Sequence[Message]:
    """The chat's messages, oldest first; 404 when it is unknown, another owner's, or no owner."""
    owner = await _chat_owner(db, owner, chat_id)
    return await list_messages(db, owner.owner_id, chat_id)


async def delete_owner_chat(db: AsyncSession, owner: CurrentOwner | None, chat_id: UUID) -> None:
    """Delete the chat; messages cascade (ADR 0009). 404 when unknown, foreign, or no owner."""
    if owner is None or not await delete_chat(db, owner.owner_id, chat_id):
        raise _not_found()
    await db.commit()


async def post_user_message(
    db: AsyncSession, owner: CurrentOwner | None, chat_id: UUID, content: str
) -> PostedMessage:
    """Store the user's message and commit, before any LLM call (ADR 0008).

    404 for a chat that is unknown or not the owner's, so foreign ids take no rate-limit
    slot; then 429 over CHAT_MESSAGES_PER_HOUR_<tier>; then 401 when the owner was deleted.
    """
    owner = await _chat_owner(db, owner, chat_id)
    owner_id = owner.owner_id
    limit = get_settings().limits(owner.tier).chat_messages_per_hour
    retry_after = chat_messages.hit(str(owner_id), limit)
    if retry_after is not None:
        raise rate_limited(retry_after)
    await lock_write_owner(db, owner)
    if not await insert_user_message(db, owner_id, chat_id, content):
        raise _not_found()
    await db.commit()
    return PostedMessage(owner_id, chat_id, content)


async def stream_reply(db: AsyncSession, posted: PostedMessage) -> AsyncIterator[ChatEvent]:
    """Stream the answer as `token` events, store it, then send `citations` and `done`.

    A provider failure, or a database error while storing the answer, sends one `error`
    event instead of `citations` and `done`, possibly after `token` events. A provider
    failure stores no assistant row. A cancelled stream (client disconnect) stores nothing.
    """
    final: Answer | None = None
    streamed = False
    try:
        async for part in stream_answer_question(db, posted.owner_id, posted.content):
            if isinstance(part, str):
                streamed = True
                yield "token", {"text": part}
            else:
                final = part
        if final is None:
            raise RuntimeError("stream_answer ended without an Answer")
    except Exception as exc:
        _log_answer_failed(posted.chat_id, exc)
        yield ANSWER_FAILED_EVENT
        return
    if not streamed:
        yield "token", {"text": final["answer"]}
    try:
        await _store_answer(db, posted.chat_id, final)
    except SQLAlchemyError as exc:
        _log_answer_failed(posted.chat_id, exc)
        await _rollback_quietly(db)
        yield ANSWER_FAILED_EVENT
        return
    yield "citations", final["citations"]
    yield "done", {}


async def _store_answer(db: AsyncSession, chat_id: UUID, final: Answer) -> None:
    """Insert the assistant row and commit; a chat deleted meanwhile stores nothing (R12)."""
    try:
        citations = [dict(citation) for citation in final["citations"]]
        stored = await insert_assistant_message(db, chat_id, final["answer"], citations)
        if stored:
            await db.commit()
    except IntegrityError:
        # The chat was deleted between the INSERT's SELECT and its foreign key check.
        stored = False
    if not stored:
        await db.rollback()
        logger.info("Chat %s is gone; assistant message not stored", chat_id)


def _log_answer_failed(chat_id: UUID, exc: Exception) -> None:
    # Exception text may quote the question, answer or chunks, so log only its type.
    logger.warning("Answer failed for chat %s: %s", chat_id, type(exc).__name__)


async def _rollback_quietly(db: AsyncSession) -> None:
    """Roll back after a failed store; a dead connection must not raise out of the stream."""
    try:
        await db.rollback()
    except SQLAlchemyError:
        logger.warning("Rollback failed after a failed answer store")


async def _chat_owner(db: AsyncSession, owner: CurrentOwner | None, chat_id: UUID) -> CurrentOwner:
    """`owner` when `chat_id` is its chat; 404 when unknown, another owner's, or no owner."""
    if owner is None or await get_chat(db, owner.owner_id, chat_id) is None:
        raise _not_found()
    return owner


def _not_found() -> AppError:
    return AppError(404, "not_found", "Chat not found")
