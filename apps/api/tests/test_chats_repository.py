import uuid
from typing import Any
from uuid import UUID

import pytest
from conftest import Sessions, add_owner, count, in_session
from sqlalchemy import Engine, text

from app.repositories.chats import (
    get_chat,
    insert_assistant_message,
    insert_chat,
    insert_user_message,
    list_chats,
    list_messages,
)

pytestmark = pytest.mark.integration


def new_chat(db_sessions: Sessions, owner_id: UUID, title: str | None = None) -> UUID:
    return in_session(db_sessions, lambda db: insert_chat(db, owner_id, title)).id


def say(db_sessions: Sessions, owner_id: UUID, chat_id: UUID, content: str) -> bool:
    return in_session(db_sessions, lambda db: insert_user_message(db, owner_id, chat_id, content))


def answer(
    db_sessions: Sessions,
    chat_id: UUID,
    content: str,
    citations: list[dict[str, Any]] | None = None,
) -> bool:
    return in_session(
        db_sessions, lambda db: insert_assistant_message(db, chat_id, content, citations or [])
    )


def history(db_sessions: Sessions, owner_id: UUID, chat_id: UUID) -> list[tuple[str, str]]:
    messages = in_session(db_sessions, lambda db: list_messages(db, owner_id, chat_id))
    return [(m.role, m.content) for m in messages]


@pytest.fixture
def owner(db_sessions: Sessions, db_engine: Engine) -> UUID:
    return add_owner(db_engine)


def test_chats_list_newest_first_and_messages_oldest_first(
    db_sessions: Sessions, owner: UUID
) -> None:
    first = new_chat(db_sessions, owner, "first")
    second = new_chat(db_sessions, owner)
    assert say(db_sessions, owner, first, "q1")
    assert answer(db_sessions, first, "a1")
    assert say(db_sessions, owner, first, "q2")

    chats = in_session(db_sessions, lambda db: list_chats(db, owner))

    assert [(c.id, c.title) for c in chats] == [(second, None), (first, "first")]
    assert history(db_sessions, owner, first) == [
        ("user", "q1"),
        ("assistant", "a1"),
        ("user", "q2"),
    ]
    assert history(db_sessions, owner, second) == []


def test_another_owners_chat_is_invisible_and_rejects_user_messages(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    stranger = add_owner(db_engine)
    chat = new_chat(db_sessions, owner)
    assert say(db_sessions, owner, chat, "mine")

    assert in_session(db_sessions, lambda db: get_chat(db, stranger, chat)) is None
    assert in_session(db_sessions, lambda db: get_chat(db, owner, chat)) is not None
    assert in_session(db_sessions, lambda db: list_chats(db, stranger)) == []
    assert history(db_sessions, stranger, chat) == []
    assert not say(db_sessions, stranger, chat, "intrusion")
    assert not say(db_sessions, owner, uuid.uuid4(), "no such chat")
    assert count(db_engine, "messages") == 1


def test_assistant_message_follows_the_chat_across_owners_until_deleted(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    user = add_owner(db_engine)
    chat = new_chat(db_sessions, owner)
    assert say(db_sessions, owner, chat, "q")
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE chats SET owner_id = :user WHERE id = :id"), {"user": user, "id": chat}
        )

    assert answer(db_sessions, chat, "a")
    assert history(db_sessions, user, chat) == [("user", "q"), ("assistant", "a")]

    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM chats WHERE id = :id"), {"id": chat})

    assert not answer(db_sessions, chat, "late")
    assert count(db_engine, "messages") == 0


def test_assistant_citations_store_uuids_as_str(db_sessions: Sessions, owner: UUID) -> None:
    chat = new_chat(db_sessions, owner)
    document_id = uuid.uuid4()
    citations = [
        {"document_id": document_id, "source": "doc.pdf", "page": 2},
        {"document_id": document_id, "source": "https://example.com", "page": None},
    ]

    assert answer(db_sessions, chat, "a", citations)

    (message,) = in_session(db_sessions, lambda db: list_messages(db, owner, chat))
    assert message.citations == [
        {"document_id": str(document_id), "source": "doc.pdf", "page": 2},
        {"document_id": str(document_id), "source": "https://example.com", "page": None},
    ]
