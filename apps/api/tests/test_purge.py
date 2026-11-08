"""Guest purge (ADR 0009, R10, R14): the worker removes expired guests, objects and rows."""

import logging
from uuid import UUID

import pytest
from botocore.exceptions import ClientError
from conftest import (
    Objects,
    Sessions,
    add_chat_with_message,
    add_guest,
    add_ready_document,
    add_user,
    axis,
    count,
    owned_count,
    run,
)
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.repositories import purge as purge_repo
from app.workers import purge

pytestmark = pytest.mark.integration

PURGED_TABLES = ("owners", "guests", "documents", "chunks", "chats", "messages")


def s3_error(code: str, status: int) -> ClientError:
    return ClientError(
        {
            "Error": {"Code": code, "Message": "secret-detail"},
            "ResponseMetadata": {"HTTPStatusCode": status},
        },
        "DeleteObject",
    )


@pytest.fixture
def purge_db(db_sessions: Sessions, monkeypatch: pytest.MonkeyPatch) -> Sessions:
    """Point the purge at the emptied test database."""
    monkeypatch.setattr(purge, "get_sessionmaker", lambda: db_sessions)
    return db_sessions


def guest_with_data(
    db_engine: Engine,
    db_sessions: Sessions,
    fake_storage: Objects,
    expires_in: float,
    source: str = "doc.pdf",
) -> tuple[UUID, UUID]:
    """A guest with one stored ready document and one chat holding a message."""
    owner = add_guest(db_engine, expires_in)
    doc = add_ready_document(db_engine, db_sessions, owner, {"fact": axis(0)}, source=source)
    fake_storage[storage.document_key(doc)] = (b"raw", "text/plain")
    add_chat_with_message(db_sessions, owner)
    return owner, doc


def test_expired_guest_is_removed_with_its_rows_and_objects(
    db_engine: Engine,
    purge_db: Sessions,
    fake_storage: Objects,
    deleted_keys: list[str],
) -> None:
    _, doc = guest_with_data(db_engine, purge_db, fake_storage, -10)

    assert run(purge.purge_expired()) == 1

    for table in PURGED_TABLES:
        assert count(db_engine, table) == 0, table
    assert deleted_keys == [storage.document_key(doc)]
    assert fake_storage == {}


def test_live_guest_and_user_are_untouched(
    db_engine: Engine,
    purge_db: Sessions,
    fake_storage: Objects,
    deleted_keys: list[str],
) -> None:
    _, live_doc = guest_with_data(db_engine, purge_db, fake_storage, 1000)
    user = add_user(db_engine, 1000)
    add_ready_document(db_engine, purge_db, user, {"fact": axis(0)})
    tables = ("owners", "guests", "users", "documents", "chats", "messages", "sessions")
    before = {table: count(db_engine, table) for table in tables}

    assert run(purge.purge_expired()) == 0

    assert {table: count(db_engine, table) for table in tables} == before
    assert deleted_keys == []
    assert f"documents/{live_doc}" in fake_storage


def test_guest_migrated_after_selection_is_skipped_and_its_data_kept(
    db_engine: Engine,
    purge_db: Sessions,
    fake_storage: Objects,
    deleted_keys: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guest, doc = guest_with_data(db_engine, purge_db, fake_storage, -10)
    user = add_user(db_engine, 1000)
    select = purge_repo.expired_guest_owner_ids

    async def select_then_migrate(db: AsyncSession, limit: int) -> list[UUID]:
        ids = await select(db, limit)
        # A login moves the guest's rows to its user, then deletes the guest owner.
        with db_engine.begin() as conn:
            params = {"g": guest, "u": user}
            conn.execute(text("UPDATE documents SET owner_id = :u WHERE owner_id = :g"), params)
            conn.execute(text("UPDATE chats SET owner_id = :u WHERE owner_id = :g"), params)
            conn.execute(text("DELETE FROM owners WHERE id = :g"), params)
        return ids

    monkeypatch.setattr(purge_repo, "expired_guest_owner_ids", select_then_migrate)

    assert run(purge.purge_expired()) == 0

    assert deleted_keys == []
    assert f"documents/{doc}" in fake_storage
    assert (owned_count(db_engine, "documents", user), owned_count(db_engine, "chats", user)) == (
        1,
        1,
    )
    assert count(db_engine, "messages") == 1


def test_s3_failure_stops_the_batch_and_keeps_every_guest_then_the_next_run_finishes(
    db_engine: Engine,
    purge_db: Sessions,
    fake_storage: Objects,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guests = [
        guest_with_data(db_engine, purge_db, fake_storage, expires_in)
        for expires_in in (-100, -50, -30)  # oldest first
    ]
    add_user(db_engine, -10)
    real_delete = storage.delete_object
    store = {"down": True}
    attempts: list[str] = []

    async def flaky(key: str) -> None:
        attempts.append(key)
        if store["down"]:
            raise ClientError({"Error": {"Code": "InternalError", "Message": "down"}}, "Delete")
        await real_delete(key)

    monkeypatch.setattr(storage, "delete_object", flaky)

    assert run(purge.purge_expired()) == 0

    assert attempts == [storage.document_key(guests[0][1])]
    assert count(db_engine, "guests") == 3
    assert (count(db_engine, "documents"), count(db_engine, "chunks")) == (3, 3)
    assert (count(db_engine, "chats"), count(db_engine, "messages")) == (3, 3)
    assert count(db_engine, "sessions") == 0
    assert count(db_engine, "users") == 1
    assert len(fake_storage) == 3

    store["down"] = False

    assert run(purge.purge_expired()) == 3

    assert count(db_engine, "guests") == 0
    assert (count(db_engine, "documents"), count(db_engine, "chunks")) == (0, 0)
    assert (count(db_engine, "chats"), count(db_engine, "messages")) == (0, 0)
    assert fake_storage == {}


def test_access_denied_skips_only_that_guest_and_the_batch_goes_on(
    db_engine: Engine,
    purge_db: Sessions,
    fake_storage: Objects,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = "https://example.com/doc?token=url-secret"
    failing, failing_doc = guest_with_data(db_engine, purge_db, fake_storage, -100, source=source)
    for expires_in in (-50, -30):
        guest_with_data(db_engine, purge_db, fake_storage, expires_in)
    denied_key = storage.document_key(failing_doc)
    real_delete = storage.delete_object

    async def denies_the_oldest(key: str) -> None:
        if key == denied_key:
            raise s3_error("AccessDenied", 403)
        await real_delete(key)

    monkeypatch.setattr(storage, "delete_object", denies_the_oldest)
    caplog.set_level(logging.WARNING, logger=purge.__name__)

    assert run(purge.purge_expired()) == 2

    assert count(db_engine, "guests") == 1
    assert (
        owned_count(db_engine, "documents", failing),
        owned_count(db_engine, "chats", failing),
    ) == (
        1,
        1,
    )
    assert count(db_engine, "messages") == 1
    assert list(fake_storage) == [denied_key]
    assert f"owner {failing}" in caplog.text
    assert "AccessDenied" in caplog.text
    assert denied_key not in caplog.text
    assert source not in caplog.text


def test_store_error_500_or_more_stops_the_batch_and_keeps_every_guest(
    db_engine: Engine,
    purge_db: Sessions,
    fake_storage: Objects,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    guests = [
        guest_with_data(db_engine, purge_db, fake_storage, expires_in)
        for expires_in in (-100, -50, -30)  # oldest first
    ]
    add_user(db_engine, -10)
    attempts: list[str] = []

    async def unavailable(key: str) -> None:
        attempts.append(key)
        raise s3_error("ServiceUnavailable", 503)

    monkeypatch.setattr(storage, "delete_object", unavailable)

    assert run(purge.purge_expired()) == 0

    assert attempts == [storage.document_key(guests[0][1])]
    assert count(db_engine, "guests") == 3
    assert (count(db_engine, "documents"), count(db_engine, "chunks")) == (3, 3)
    assert (count(db_engine, "chats"), count(db_engine, "messages")) == (3, 3)
    assert count(db_engine, "sessions") == 0
    assert len(fake_storage) == 3


def test_a_database_error_skips_that_guest_and_the_batch_goes_on(
    db_engine: Engine,
    purge_db: Sessions,
    fake_storage: Objects,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing, _ = guest_with_data(db_engine, purge_db, fake_storage, -100)  # oldest
    guest_with_data(db_engine, purge_db, fake_storage, -50)
    delete_owned_rows = purge_repo.delete_owned_rows

    async def broken_for_one(db: AsyncSession, owner_id: UUID) -> None:
        if owner_id == failing:
            raise RuntimeError("database hiccup")
        await delete_owned_rows(db, owner_id)

    monkeypatch.setattr(purge_repo, "delete_owned_rows", broken_for_one)

    assert run(purge.purge_expired()) == 1

    assert count(db_engine, "guests") == 1
    assert owned_count(db_engine, "documents", failing) == 1
    assert owned_count(db_engine, "chats", failing) == 1


def test_expired_sessions_are_removed_and_live_ones_kept(
    db_engine: Engine, purge_db: Sessions
) -> None:
    add_user(db_engine, -10)
    add_user(db_engine, 1000)

    assert run(purge.purge_expired()) == 0

    assert count(db_engine, "sessions") == 1
    assert count(db_engine, "users") == 2


def test_one_run_purges_at_most_a_batch(
    db_engine: Engine, purge_db: Sessions, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(purge, "PURGE_BATCH", 2)
    for expires_in in (-30, -20, -10):
        add_guest(db_engine, expires_in)

    assert run(purge.purge_expired()) == 2
    assert count(db_engine, "guests") == 1
    assert run(purge.purge_expired()) == 1
    assert count(db_engine, "guests") == 0


def test_logs_hold_owner_ids_and_counts_never_a_source_or_error_text(
    db_engine: Engine,
    purge_db: Sessions,
    fake_storage: Objects,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = "https://example.com/doc?token=url-secret"
    failing, doc = guest_with_data(db_engine, purge_db, fake_storage, -10)
    add_guest(db_engine, -5)
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE documents SET source = :s WHERE id = :id"), {"s": source, "id": doc}
        )

    async def always_fails(key: str) -> None:
        raise ClientError(
            {"Error": {"Code": "InternalError", "Message": "secret-detail"}}, "Delete"
        )

    monkeypatch.setattr(storage, "delete_object", always_fails)
    caplog.set_level(logging.INFO, logger=purge.__name__)

    assert run(purge.purge_expired()) == 0

    assert f"Purge stopped at owner {failing}: store down (ClientError)" in caplog.text
    assert "Purged 0 of 2 expired guests and 0 sessions" in caplog.text
    assert "url-secret" not in caplog.text
    assert "secret-detail" not in caplog.text
