from uuid import UUID

import pytest
from conftest import (
    Sessions,
    add_chat_with_message,
    add_document,
    add_guest,
    add_owner,
    add_ready_document,
    add_user,
    count,
    in_session,
    owned_count,
)
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.chats import delete_chat
from app.repositories.documents import delete_document
from app.repositories.owners import delete_owner
from app.repositories.purge import (
    delete_expired_sessions,
    delete_owned_rows,
    expired_guest_owner_ids,
    guest_expired,
    owner_document_ids,
)

pytestmark = pytest.mark.integration


def test_delete_document_removes_row_and_chunks(db_engine: Engine, db_sessions: Sessions) -> None:
    owner = add_owner(db_engine)
    doc = add_ready_document(db_engine, db_sessions, owner, {"a": [1.0] * 8})
    assert count(db_engine, "chunks") == 1
    assert in_session(db_sessions, lambda db: delete_document(db, owner, doc))
    assert count(db_engine, "documents") == 0
    assert count(db_engine, "chunks") == 0


def test_delete_document_refuses_processing_and_other_owner(
    db_engine: Engine, db_sessions: Sessions
) -> None:
    owner, other = add_owner(db_engine), add_owner(db_engine)
    busy = add_document(db_engine, owner, "processing")
    mine = add_document(db_engine, owner, "ready")
    assert not in_session(db_sessions, lambda db: delete_document(db, owner, busy))
    assert not in_session(db_sessions, lambda db: delete_document(db, other, mine))
    assert count(db_engine, "documents") == 2


def test_delete_chat_cascades_and_refuses_other_owner(
    db_engine: Engine, db_sessions: Sessions
) -> None:
    owner, other = add_owner(db_engine), add_owner(db_engine)
    chat = add_chat_with_message(db_sessions, owner)
    assert not in_session(db_sessions, lambda db: delete_chat(db, other, chat))
    assert count(db_engine, "chats") == 1
    assert in_session(db_sessions, lambda db: delete_chat(db, owner, chat))
    assert count(db_engine, "chats") == 0
    assert count(db_engine, "messages") == 0


def test_expired_guest_owner_ids_oldest_first_limited_expired_guests_only(
    db_engine: Engine, db_sessions: Sessions
) -> None:
    newer = add_guest(db_engine, -10)
    oldest = add_guest(db_engine, -100)
    middle = add_guest(db_engine, -50)
    add_guest(db_engine, 1000)
    add_user(db_engine, -10)

    assert in_session(db_sessions, lambda db: expired_guest_owner_ids(db, 10)) == [
        oldest,
        middle,
        newer,
    ]
    assert in_session(db_sessions, lambda db: expired_guest_owner_ids(db, 2)) == [oldest, middle]


def test_guest_expired_only_for_an_existing_expired_guest(
    db_engine: Engine, db_sessions: Sessions
) -> None:
    expired, live = add_guest(db_engine, -10), add_guest(db_engine, 1000)
    migrated = add_user(db_engine)

    def check(owner: UUID) -> bool:
        return in_session(db_sessions, lambda db: guest_expired(db, owner))

    assert check(expired)
    assert not check(live)
    assert not check(migrated)
    assert not check(UUID(int=1))


def test_delete_owned_rows_then_owner_leaves_nothing_of_that_owner(
    db_engine: Engine, db_sessions: Sessions
) -> None:
    gone, kept = add_guest(db_engine, -10), add_guest(db_engine, 1000)
    docs = {
        o: add_ready_document(db_engine, db_sessions, o, {"a": [1.0] * 8}) for o in (gone, kept)
    }
    for o in (gone, kept):
        add_chat_with_message(db_sessions, o)
    assert in_session(db_sessions, lambda db: owner_document_ids(db, gone)) == [docs[gone]]

    async def purge(db: AsyncSession) -> None:
        await delete_owned_rows(db, gone)
        await delete_owner(db, gone)

    in_session(db_sessions, purge)
    for table in ("documents", "chats"):
        assert owned_count(db_engine, table, gone) == 0
        assert owned_count(db_engine, table, kept) == 1
    for table in ("chunks", "messages", "guests", "owners"):
        assert count(db_engine, table) == 1
    with db_engine.connect() as conn:
        assert not conn.execute(text("SELECT 1 FROM owners WHERE id = :o"), {"o": gone}).first()


def test_delete_expired_sessions_removes_only_expired(
    db_engine: Engine, db_sessions: Sessions
) -> None:
    add_user(db_engine, -10)
    add_user(db_engine, 1000)
    assert in_session(db_sessions, delete_expired_sessions) == 1
    assert count(db_engine, "sessions") == 1
