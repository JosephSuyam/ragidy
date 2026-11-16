from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends
from fastapi.sse import EventSourceResponse, ServerSentEvent

from app.api.deps import DbSession, ReadOwner, WriteOwner
from app.schemas.chats import ChatCreate, ChatOut, MessageIn, MessageOut
from app.services import chats

router = APIRouter(prefix="/chats", tags=["chats"])


@router.post("", status_code=201)
async def create_chat(db: DbSession, owner: WriteOwner, body: ChatCreate | None = None) -> ChatOut:
    chat = await chats.create_chat(db, owner, body.title if body else None)
    return ChatOut.model_validate(chat)


@router.get("")
async def list_chats(db: DbSession, owner: ReadOwner) -> list[ChatOut]:
    return [ChatOut.model_validate(chat) for chat in await chats.list_owner_chats(db, owner)]


@router.get("/{id}/messages")
async def list_messages(id: UUID, db: DbSession, owner: ReadOwner) -> list[MessageOut]:
    messages = await chats.list_chat_messages(db, owner, id)
    return [MessageOut.model_validate(message) for message in messages]


@router.delete("/{id}", status_code=204)
async def delete_chat(id: UUID, db: DbSession, owner: ReadOwner) -> None:
    await chats.delete_owner_chat(db, owner, id)


async def _post_message(
    id: UUID, body: MessageIn, db: DbSession, owner: ReadOwner
) -> chats.PostedMessage:
    # A dependency, because SSE headers are sent before the route generator runs, so its
    # errors could no longer be 401, 404 or 429 (ADR 0008).
    return await chats.post_user_message(db, owner, id, body.content)


@router.post("/{id}/messages", response_class=EventSourceResponse)
async def post_message(
    db: DbSession, posted: Annotated[chats.PostedMessage, Depends(_post_message)]
) -> AsyncIterator[ServerSentEvent]:
    async for event, data in chats.stream_reply(db, posted):
        yield ServerSentEvent(event=event, data=data)
