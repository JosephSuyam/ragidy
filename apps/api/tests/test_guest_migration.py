import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from conftest import EMAIL, PASSWORD, app_client, count, register, set_cookies, write
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, text

from app.api.deps import GUEST_COOKIE
from app.core.errors import AppError
from app.repositories import owners
from app.services import auth
from app.services.owners import CurrentOwner

pytestmark = pytest.mark.integration


def post_auth(client: TestClient, action: str) -> Response:
    return client.post(f"/auth/{action}", json={"email": EMAIL, "password": PASSWORD})


def registered_user_owner(client: TestClient, db_engine: Engine) -> uuid.UUID:
    """Register EMAIL, then drop its session cookie, so the client is anonymous again."""
    register(client)
    client.cookies.clear()
    with db_engine.connect() as conn:
        return conn.execute(text("SELECT owner_id FROM users")).scalar_one()


def seed_documents(db_engine: Engine, owner_id: Any, n: int) -> set[uuid.UUID]:
    with db_engine.begin() as conn:
        rows = conn.execute(
            text(
                "INSERT INTO documents (owner_id, source, embed_model) "
                "SELECT :o, 'doc' || i || '.pdf', 'm' FROM generate_series(1, :n) i RETURNING id"
            ),
            {"o": owner_id, "n": n},
        )
        return set(rows.scalars())


def seed_chat(db_engine: Engine, owner_id: Any) -> uuid.UUID:
    with db_engine.begin() as conn:
        chat_id = conn.execute(
            text("INSERT INTO chats (owner_id) VALUES (:o) RETURNING id"), {"o": owner_id}
        ).scalar_one()
        conn.execute(
            text(
                "INSERT INTO messages (chat_id, role, content) "
                "VALUES (:c, 'user', 'hi'), (:c, 'assistant', 'hello')"
            ),
            {"c": chat_id},
        )
    return chat_id


def owned(db_engine: Engine, owner_id: Any) -> tuple[set[uuid.UUID], set[uuid.UUID]]:
    """The ids of the documents and chats `owner_id` owns."""
    with db_engine.connect() as conn:
        docs = conn.execute(text("SELECT id FROM documents WHERE owner_id = :o"), {"o": owner_id})
        chats = conn.execute(text("SELECT id FROM chats WHERE owner_id = :o"), {"o": owner_id})
        return set(docs.scalars()), set(chats.scalars())


@pytest.mark.parametrize("action", ["register", "login"])
def test_login_and_register_migrate_guest_rows(
    client: TestClient, db_engine: Engine, action: str
) -> None:
    if action == "login":
        registered_user_owner(client, db_engine)
    guest_owner = write(client).json()["owner_id"]
    docs = seed_documents(db_engine, guest_owner, 2)
    chat = seed_chat(db_engine, guest_owner)

    response = post_auth(client, action)
    assert response.status_code == (201 if action == "register" else 200), response.text
    cleared = set_cookies(response)[GUEST_COOKIE]
    assert (cleared.value, cleared["max-age"]) == ("", "0")

    with db_engine.connect() as conn:
        user_owner = conn.execute(text("SELECT owner_id FROM users")).scalar_one()
        messages = conn.execute(
            text("SELECT role, content FROM messages WHERE chat_id = :c"), {"c": chat}
        ).all()
        owner_ids = conn.execute(text("SELECT id FROM owners")).scalars().all()
    assert owned(db_engine, user_owner) == (docs, {chat})
    assert sorted(tuple(m) for m in messages) == [("assistant", "hello"), ("user", "hi")]
    assert owner_ids == [user_owner]
    assert count(db_engine, "guests") == 0
    assert client.get("/me").json()["document_count"] == 2


def test_migration_ignores_user_cap(
    db_override: Callable[[], AsyncIterator[Any]],
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MAX_DOCS_USER", "1")
    with app_client(db_override) as client:
        user_owner = registered_user_owner(client, db_engine)
        user_docs = seed_documents(db_engine, user_owner, 1)
        guest_docs = seed_documents(db_engine, write(client).json()["owner_id"], 2)

        assert post_auth(client, "login").status_code == 200
        me = client.get("/me").json()
    assert (me["document_count"], me["limits"]["max_docs"]) == (3, 1)
    assert owned(db_engine, user_owner)[0] == user_docs | guest_docs


@pytest.mark.parametrize("when", ["before_request", "during_request"])
def test_migration_after_purge_succeeds(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    user_owner = registered_user_owner(client, db_engine)
    guest_owner = uuid.UUID(write(client).json()["owner_id"])
    with db_engine.begin() as conn:
        conn.execute(text("DELETE FROM owners WHERE id = :g"), {"g": guest_owner})
    if when == "during_request":
        # The guest resolved, then the purge deleted its owner row before the lock.
        async def stale_guest(db: Any, token: str | None) -> CurrentOwner:
            return CurrentOwner(guest_owner, "guest", None, None)

        monkeypatch.setattr(auth, "resolve_guest", stale_guest)

    response = post_auth(client, "login")
    assert response.status_code == 200, response.text
    assert set_cookies(response)[GUEST_COOKIE]["max-age"] == "0"
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT id FROM owners")).scalars().all() == [user_owner]
    assert client.get("/me").json()["tier"] == "user"


def test_migration_failure_moves_nothing(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    guest_owner = write(client).json()["owner_id"]
    docs = seed_documents(db_engine, guest_owner, 2)
    chat = seed_chat(db_engine, guest_owner)

    async def fail_after_transfer(db: Any, owner_id: Any) -> None:
        raise AppError(503, "unavailable", "try again")

    monkeypatch.setattr(owners, "delete_owner", fail_after_transfer)
    response = post_auth(client, "register")
    assert response.status_code == 503
    assert "set-cookie" not in response.headers
    assert owned(db_engine, guest_owner) == (docs, {chat})
    # One commit per request: the user and its session roll back with the migration.
    assert [count(db_engine, t) for t in ("users", "sessions", "guests")] == [0, 0, 1]
    me = client.get("/me").json()
    assert (me["tier"], me["document_count"]) == ("guest", 2)
