import asyncio
import json
import logging
import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest
from conftest import (
    EMAIL,
    FAIL_WORD,
    ORIGIN,
    PASSWORD,
    Sessions,
    StubChatModel,
    add_owner,
    add_ready_document,
    app_client,
    axis,
    count,
    in_session,
    register,
    run,
    set_cookies,
)
from fastapi.testclient import TestClient
from httpx import Response
from llama_index.core import MockEmbedding
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.workflows import NOT_FOUND_ANSWER
from app.api.deps import GUEST_COOKIE
from app.core.config import get_settings
from app.repositories.chats import insert_assistant_message, insert_user_message
from app.services import chats
from app.services.chats import ANSWER_FAILED

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("mock_embeddings")]

GetDb = Callable[[], AsyncIterator[AsyncSession]]
QUESTION = "What is the zebra plan?"
FACT = "The zebra plan ships on Friday."
ANSWER = "It ships on Friday, per the zebra plan."
ERROR_EVENT = ("error", {"code": "answer_failed", "detail": ANSWER_FAILED})


def new_chat(client: TestClient, title: str | None = None) -> str:
    response = client.post("/chats", json={"title": title})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def owner_of(db_engine: Engine, chat_id: str) -> uuid.UUID:
    with db_engine.connect() as conn:
        return conn.execute(
            text("SELECT owner_id FROM chats WHERE id = :c"), {"c": chat_id}
        ).scalar_one()


def add_chat(db_engine: Engine, owner_id: uuid.UUID) -> str:
    with db_engine.begin() as conn:
        return str(
            conn.execute(
                text("INSERT INTO chats (owner_id) VALUES (:o) RETURNING id"), {"o": owner_id}
            ).scalar_one()
        )


def migrate_owner(db_engine: Engine, guest_owner: uuid.UUID, user_owner: uuid.UUID) -> None:
    """What a guest migration does: move the guest's chats, then delete its owner row."""
    with db_engine.begin() as conn:
        params = {"g": guest_owner, "u": user_owner}
        conn.execute(text("UPDATE chats SET owner_id = :u WHERE owner_id = :g"), params)
        conn.execute(text("DELETE FROM owners WHERE id = :g"), params)


def add_doc(db_engine: Engine, db_sessions: Sessions, owner_id: uuid.UUID) -> uuid.UUID:
    """A ready one-chunk document holding FACT, embedded by the configured embed model."""
    return add_ready_document(
        db_engine, db_sessions, owner_id, {FACT: axis(0)}, model=get_settings().embed_model
    )


def chat_with_doc(
    client: TestClient, db_engine: Engine, db_sessions: Sessions
) -> tuple[str, uuid.UUID]:
    chat_id = new_chat(client)
    return chat_id, add_doc(db_engine, db_sessions, owner_of(db_engine, chat_id))


def cited(doc: uuid.UUID) -> list[dict[str, Any]]:
    return [{"document_id": str(doc), "source": "doc.pdf", "page": 1, "snippet": FACT}]


def send(client: TestClient, chat_id: str, content: str = QUESTION) -> Response:
    return client.post(f"/chats/{chat_id}/messages", json={"content": content})


def events(response: Response) -> list[tuple[str, Any]]:
    """The response's SSE events as (name, decoded data); keep-alive comments are skipped."""
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/event-stream")
    parsed = []
    for block in response.text.replace("\r\n", "\n").split("\n\n"):
        fields = dict(
            line.split(":", 1) for line in block.split("\n") if line and not line.startswith(":")
        )
        if fields:
            parsed.append((fields["event"].strip(), json.loads(fields["data"])))
    return parsed


def post_message(
    client: TestClient, chat_id: str, content: str = QUESTION
) -> list[tuple[str, Any]]:
    return events(send(client, chat_id, content))


def history(client: TestClient, chat_id: str) -> list[dict[str, Any]]:
    response = client.get(f"/chats/{chat_id}/messages")
    assert response.status_code == 200, response.text
    return response.json()


def user_message(content: str = QUESTION) -> dict[str, Any]:
    return {"role": "user", "content": content, "citations": []}


def test_create_chat_for_new_guest_sets_cookie(client: TestClient, db_engine: Engine) -> None:
    response = client.post("/chats", json={"title": "Notes"})

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"id", "title", "created_at"}
    assert body["title"] == "Notes"
    assert GUEST_COOKIE in set_cookies(response)
    assert count(db_engine, "guests") == 1
    with db_engine.connect() as conn:
        guest_owner = conn.execute(text("SELECT owner_id FROM guests")).scalar_one()
    assert owner_of(db_engine, body["id"]) == guest_owner


def test_create_chat_without_body_has_no_title(client: TestClient) -> None:
    response = client.post("/chats")

    assert response.status_code == 201, response.text
    assert response.json()["title"] is None


@pytest.mark.parametrize("title", ["t" * 201, "a\u0000b"])
def test_create_chat_title_over_200_chars_or_with_nul_422(
    client: TestClient, db_engine: Engine, title: str
) -> None:
    response = client.post("/chats", json={"title": title})

    assert response.status_code == 422, response.text
    assert (count(db_engine, "chats"), count(db_engine, "guests")) == (0, 0)


def test_list_chats_newest_first(client: TestClient) -> None:
    first, second = new_chat(client, "first"), new_chat(client, "second")

    response = client.get("/chats")

    assert response.status_code == 200, response.text
    assert [c["id"] for c in response.json()] == [second, first]


def test_list_chats_without_owner_is_empty_and_creates_no_guest(
    client: TestClient, db_engine: Engine
) -> None:
    add_chat(db_engine, add_owner(db_engine))

    response = client.get("/chats")

    assert response.status_code == 200, response.text
    assert response.json() == []
    assert "set-cookie" not in response.headers
    assert count(db_engine, "guests") == 0


def test_list_messages_oldest_first_with_citations(client: TestClient, db_engine: Engine) -> None:
    chat_id = new_chat(client)
    doc = uuid.uuid4()
    rows = [
        ("user", "first?", "[]"),
        ("assistant", "first.", json.dumps(cited(doc))),
        ("user", "second?", "[]"),
    ]
    for role, content, citations in rows:  # one transaction each, so created_at increases
        with db_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO messages (chat_id, role, content, citations) "
                    "VALUES (:c, :r, :t, CAST(:j AS jsonb))"
                ),
                {"c": chat_id, "r": role, "t": content, "j": citations},
            )

    assert history(client, chat_id) == [
        user_message("first?"),
        {"role": "assistant", "content": "first.", "citations": cited(doc)},
        user_message("second?"),
    ]


def test_list_messages_of_another_owners_chat_404(client: TestClient, db_engine: Engine) -> None:
    new_chat(client)
    foreign = add_chat(db_engine, add_owner(db_engine))

    response = client.get(f"/chats/{foreign}/messages")

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not_found"


def test_list_messages_without_owner_404(client: TestClient, db_engine: Engine) -> None:
    chat_id = add_chat(db_engine, add_owner(db_engine))

    response = client.get(f"/chats/{chat_id}/messages")

    assert response.status_code == 404, response.text
    assert "set-cookie" not in response.headers
    assert count(db_engine, "guests") == 0


def test_post_message_streams_tokens_then_citations_then_done(
    client: TestClient,
    db_engine: Engine,
    db_sessions: Sessions,
    streaming_replies: Callable[..., None],
) -> None:
    chat_id, doc = chat_with_doc(client, db_engine, db_sessions)
    streaming_replies('{"relevant": [0]}', ANSWER)

    stream = post_message(client, chat_id, f"  {QUESTION}  ")

    *tokens, citations, done = stream
    assert len(tokens) > 1
    assert {name for name, _ in tokens} == {"token"}
    assert "".join(data["text"] for _, data in tokens) == ANSWER
    assert (citations, done) == (("citations", cited(doc)), ("done", {}))
    assert history(client, chat_id) == [
        user_message(),
        {"role": "assistant", "content": ANSWER, "citations": cited(doc)},
    ]
    with db_engine.connect() as conn:
        stored = conn.execute(text("SELECT citations FROM messages WHERE role = 'assistant'"))
        assert stored.scalar_one() == cited(doc)


def test_post_message_without_ready_documents_answers_not_found_without_llm(
    client: TestClient, chat_model: StubChatModel
) -> None:
    chat_id = new_chat(client)

    stream = post_message(client, chat_id)

    assert stream == [("token", {"text": NOT_FOUND_ANSWER}), ("citations", []), ("done", {})]
    assert chat_model.calls == []
    assert history(client, chat_id) == [
        user_message(),
        {"role": "assistant", "content": NOT_FOUND_ANSWER, "citations": []},
    ]


def test_post_message_over_hourly_limit_429_before_llm_and_foreign_ids_take_no_slot(
    db_override: GetDb,
    db_engine: Engine,
    db_sessions: Sessions,
    chat_model: StubChatModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHAT_MESSAGES_PER_HOUR_GUEST", "1")
    foreign = add_chat(db_engine, add_owner(db_engine))
    with app_client(db_override) as client:
        chat_id, _ = chat_with_doc(client, db_engine, db_sessions)
        assert send(client, foreign).status_code == 404
        chat_model.grades = [[0]]
        assert [name for name, _ in post_message(client, chat_id)] == ["token", "citations", "done"]
        llm_calls = len(chat_model.calls)

        limited = send(client, chat_id, "one more?")

        assert limited.status_code == 429, limited.text
        assert limited.json()["code"] == "rate_limited"
        assert 0 < int(limited.headers["retry-after"]) <= 3600
        assert len(chat_model.calls) == llm_calls
        assert [m["content"] for m in history(client, chat_id)] == [QUESTION, chat_model.reply]


def test_post_message_to_another_owners_chat_404(
    client: TestClient, db_engine: Engine, chat_model: StubChatModel
) -> None:
    new_chat(client)
    foreign = add_chat(db_engine, add_owner(db_engine))

    response = send(client, foreign)

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not_found"
    assert count(db_engine, "messages") == 0
    assert chat_model.calls == []


@pytest.mark.parametrize("content", ["", "   \n\t ", "a" * 4001])
def test_post_message_blank_or_over_4000_chars_422(
    client: TestClient, db_engine: Engine, content: str
) -> None:
    chat_id = new_chat(client)

    response = send(client, chat_id, content)

    assert response.status_code == 422, response.text
    assert count(db_engine, "messages") == 0


def test_post_message_with_nul_422_stores_nothing_and_takes_no_rate_limit_slot(
    db_override: GetDb,
    db_engine: Engine,
    chat_model: StubChatModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("CHAT_MESSAGES_PER_HOUR_GUEST", "1")
    with app_client(db_override) as client:
        chat_id = new_chat(client)

        response = send(client, chat_id, "a\u0000b")

        assert response.status_code == 422, response.text
        assert count(db_engine, "messages") == 0
        assert post_message(client, chat_id)[-1] == ("done", {})


def test_post_message_of_4000_chars_is_accepted(
    client: TestClient, chat_model: StubChatModel
) -> None:
    chat_id = new_chat(client)

    assert post_message(client, chat_id, "a" * 4000)[-1] == ("done", {})


def test_post_message_after_owner_row_deleted_401_and_no_message(
    client: TestClient,
    db_engine: Engine,
    chat_model: StubChatModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_id = new_chat(client)
    guest_owner, user_owner = owner_of(db_engine, chat_id), add_owner(db_engine)
    get_chat = chats.get_chat

    async def get_then_migrate(db: AsyncSession, owner_id: uuid.UUID, id: uuid.UUID) -> Any:
        chat = await get_chat(db, owner_id, id)
        migrate_owner(db_engine, guest_owner, user_owner)  # before the lock
        return chat

    monkeypatch.setattr(chats, "get_chat", get_then_migrate)
    response = send(client, chat_id)

    assert response.status_code == 401, response.text
    assert response.json()["code"] == "session_expired"
    assert count(db_engine, "messages") == 0
    assert chat_model.calls == []


def test_create_chat_after_owner_row_deleted_401_and_no_chat(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    chat_id = new_chat(client)
    guest_owner, user_owner = owner_of(db_engine, chat_id), add_owner(db_engine)
    lock_write_owner = chats.lock_write_owner

    async def migrate_then_lock(db: AsyncSession, owner: Any) -> None:
        migrate_owner(db_engine, guest_owner, user_owner)
        await lock_write_owner(db, owner)

    monkeypatch.setattr(chats, "lock_write_owner", migrate_then_lock)
    response = client.post("/chats", json={"title": "late"})

    assert response.status_code == 401, response.text
    assert response.json()["code"] == "session_expired"
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT id FROM chats")).scalars().all() == [uuid.UUID(chat_id)]


@pytest.mark.parametrize("action", ["register", "login"])
def test_guest_chats_and_messages_move_to_user_on_sign_in(
    client: TestClient, db_engine: Engine, chat_model: StubChatModel, action: str
) -> None:
    if action == "login":
        register(client)
        client.cookies.clear()
    chat_id = new_chat(client, "guest chat")
    post_message(client, chat_id)
    guest_history = history(client, chat_id)

    response = client.post(f"/auth/{action}", json={"email": EMAIL, "password": PASSWORD})

    assert response.is_success, response.text
    assert [c["id"] for c in client.get("/chats").json()] == [chat_id]
    assert history(client, chat_id) == guest_history
    assert len(guest_history) == 2
    with db_engine.connect() as conn:
        user_owner = conn.execute(text("SELECT owner_id FROM users")).scalar_one()
    assert owner_of(db_engine, chat_id) == user_owner
    assert count(db_engine, "guests") == 0


def test_provider_failure_sends_only_an_error_event_and_stores_no_answer(
    client: TestClient, db_engine: Engine, db_sessions: Sessions, chat_model: StubChatModel
) -> None:
    chat_id, _ = chat_with_doc(client, db_engine, db_sessions)
    chat_model.grades = [[0]]

    def fail_at_generate() -> None:
        if chat_model.calls:  # the grade went through; generate fails
            raise RuntimeError("provider echoed the prompt: zebra")

    chat_model.on_call = fail_at_generate
    response = send(client, chat_id)

    assert events(response) == [ERROR_EVENT]
    assert "zebra" not in response.text.lower()
    assert history(client, chat_id) == [user_message()]


def test_provider_failure_mid_stream_sends_tokens_then_error_and_stores_no_answer(
    client: TestClient,
    db_engine: Engine,
    db_sessions: Sessions,
    streaming_replies: Callable[..., None],
) -> None:
    chat_id, _ = chat_with_doc(client, db_engine, db_sessions)
    streaming_replies('{"relevant": [0]}', f"It ships {FAIL_WORD} on Friday")

    *tokens, last = post_message(client, chat_id)

    assert {name for name, _ in tokens} == {"token"}
    assert "".join(data["text"] for _, data in tokens) == "It ships "
    assert last == ERROR_EVENT
    assert history(client, chat_id) == [user_message()]


@pytest.mark.parametrize("error", [OperationalError, IntegrityError])
def test_store_failure_after_tokens_stores_no_answer_and_logs_no_text(
    client: TestClient,
    db_engine: Engine,
    db_sessions: Sessions,
    streaming_replies: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: type[OperationalError | IntegrityError],
) -> None:
    """IntegrityError means the chat is gone, so the stream still ends normally (R12)."""
    chat_id, doc = chat_with_doc(client, db_engine, db_sessions)
    streaming_replies('{"relevant": [0]}', ANSWER)

    async def fail_insert(*args: Any) -> bool:
        raise error("INSERT INTO messages", {"content": ANSWER}, Exception(QUESTION))

    monkeypatch.setattr(chats, "insert_assistant_message", fail_insert)
    caplog.set_level(logging.DEBUG)

    stream = post_message(client, chat_id)

    gone = error is IntegrityError
    tail = [("citations", cited(doc)), ("done", {})] if gone else [ERROR_EVENT]
    tokens = stream[: -len(tail)]
    assert stream[-len(tail) :] == tail
    assert {name for name, _ in tokens} == {"token"}
    assert "".join(data["text"] for _, data in tokens) == ANSWER
    assert history(client, chat_id) == [user_message()]
    expected_log = f"Chat {chat_id} is gone" if gone else "Answer failed for chat"
    assert expected_log in caplog.text
    logged = caplog.text + "".join(record.getMessage() for record in caplog.records)
    assert QUESTION not in logged
    assert ANSWER not in logged


def test_chat_deleted_mid_stream_still_ends_with_citations_and_done(
    client: TestClient,
    db_engine: Engine,
    db_sessions: Sessions,
    chat_model: StubChatModel,
    caplog: pytest.LogCaptureFixture,
) -> None:
    chat_id, doc = chat_with_doc(client, db_engine, db_sessions)
    chat_model.grades = [[0]]

    def delete_chat() -> None:
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM chats WHERE id = :c"), {"c": chat_id})

    chat_model.on_call = delete_chat
    caplog.set_level(logging.INFO, logger=chats.__name__)

    stream = post_message(client, chat_id)

    assert stream == [
        ("token", {"text": chat_model.reply}),
        ("citations", cited(doc)),
        ("done", {}),
    ]
    assert (count(db_engine, "chats"), count(db_engine, "messages")) == (0, 0)
    assert f"Chat {chat_id} is gone" in caplog.text


def test_no_transaction_is_open_during_embedding_or_chat_calls_while_streaming(
    db_sessions: Sessions,
    db_engine: Engine,
    chat_model: StubChatModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[AsyncSession] = []

    async def recording_db() -> AsyncIterator[AsyncSession]:
        async with db_sessions() as session:
            opened.append(session)
            yield session

    in_transaction: dict[str, list[bool]] = {"embed": [], "chat": []}

    def any_open() -> bool:
        return any(session.in_transaction() for session in opened)

    async def embed(self: MockEmbedding, query: str) -> list[float]:
        in_transaction["embed"].append(any_open())
        return axis(0)

    monkeypatch.setattr(MockEmbedding, "aget_query_embedding", embed)
    chat_model.on_call = lambda: in_transaction["chat"].append(any_open())
    chat_model.grades = [[0]]
    with app_client(recording_db) as client:
        chat_id, _ = chat_with_doc(client, db_engine, db_sessions)

        assert post_message(client, chat_id)[-1] == ("done", {})

    # One retrieval; grade, generate.
    assert in_transaction == {"embed": [False], "chat": [False, False]}


@pytest.mark.parametrize("fails", [False, True])
def test_question_and_answer_never_logged_while_streaming(
    client: TestClient,
    db_engine: Engine,
    db_sessions: Sessions,
    chat_model: StubChatModel,
    caplog: pytest.LogCaptureFixture,
    fails: bool,
) -> None:
    chat_id, _ = chat_with_doc(client, db_engine, db_sessions)
    chat_model.grades = [[0]]
    chat_model.reply = ANSWER

    def maybe_fail() -> None:
        if fails and chat_model.calls:
            raise RuntimeError(f"provider echoed {QUESTION}")

    chat_model.on_call = maybe_fail
    caplog.set_level(logging.DEBUG)

    stream = post_message(client, chat_id)

    assert (stream == [ERROR_EVENT]) is fails
    assert ("Answer failed" in caplog.text) is fails  # the capture sees the app's logs
    logged = caplog.text + "".join(record.getMessage() for record in caplog.records)
    assert QUESTION not in logged
    assert ANSWER not in logged


def post_then_disconnect(
    client: TestClient, chat_id: str, gate: asyncio.Event | None = None
) -> bytes:
    """POST QUESTION to `chat_id` as raw ASGI and disconnect once `gate` is set.

    `gate` defaults to the first token event. TestClient and httpx's ASGITransport only report
    a disconnect once the response is done.
    """
    from app.main import app

    first_token = asyncio.Event()
    disconnect = first_token if gate is None else gate
    body: list[bytes] = []
    request = iter([{"type": "http.request", "body": json.dumps({"content": QUESTION}).encode()}])

    async def receive() -> dict[str, Any]:
        if (message := next(request, None)) is not None:
            return message
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict[str, Any]) -> None:
        if message["type"] == "http.response.body":
            body.append(message["body"])
            if b"event: token" in message["body"]:
                first_token.set()

    cookie = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": f"/chats/{chat_id}/messages",
        "raw_path": f"/chats/{chat_id}/messages".encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [
            (b"host", b"testserver"),
            (b"origin", ORIGIN.encode()),
            (b"content-type", b"application/json"),
            (b"cookie", cookie.encode()),
        ],
        "client": ("127.0.0.1", 50000),
        "server": ("testserver", 80),
    }
    run(app(scope, receive, send))
    return b"".join(body)


def test_client_disconnect_mid_stream_stores_no_answer(
    client: TestClient,
    db_engine: Engine,
    db_sessions: Sessions,
    streaming_replies: Callable[..., None],
) -> None:
    chat_id, _ = chat_with_doc(client, db_engine, db_sessions)
    # Far more tokens than the SSE producer runs ahead of the client (about 2 events).
    streaming_replies('{"relevant": [0]}', " ".join(["word"] * 30))

    body = post_then_disconnect(client, chat_id)

    assert b"event: token" in body
    assert b"event: done" not in body
    assert history(client, chat_id) == [user_message()]


def add_answer(db_sessions: Sessions, chat_id: str, doc: uuid.UUID) -> None:
    """An assistant answer citing `doc`, stored as the answer stream stores it."""
    in_session(
        db_sessions,
        lambda db: insert_assistant_message(db, uuid.UUID(chat_id), ANSWER, cited(doc)),
    )


def test_delete_chat_removes_chat_and_messages_then_404(
    client: TestClient, db_engine: Engine, db_sessions: Sessions
) -> None:
    chat_id = new_chat(client)
    owner = owner_of(db_engine, chat_id)
    in_session(db_sessions, lambda db: insert_user_message(db, owner, uuid.UUID(chat_id), QUESTION))

    response = client.delete(f"/chats/{chat_id}")

    assert response.status_code == 204, response.text
    assert response.content == b""
    assert (count(db_engine, "chats"), count(db_engine, "messages")) == (0, 0)
    again = client.delete(f"/chats/{chat_id}")
    assert again.status_code == 404, again.text
    assert again.json()["code"] == "not_found"


def test_delete_another_owners_chat_404_and_keeps_it(
    client: TestClient, db_engine: Engine, db_sessions: Sessions
) -> None:
    new_chat(client)
    theirs_owner = add_owner(db_engine)
    theirs = add_chat(db_engine, theirs_owner)
    in_session(
        db_sessions, lambda db: insert_user_message(db, theirs_owner, uuid.UUID(theirs), QUESTION)
    )

    response = client.delete(f"/chats/{theirs}")

    assert response.status_code == 404, response.text
    assert response.json()["code"] == "not_found"
    assert (count(db_engine, "chats"), count(db_engine, "messages")) == (2, 1)


def test_delete_chat_without_a_cookie_404_and_creates_no_guest(
    client: TestClient, db_engine: Engine
) -> None:
    theirs = add_chat(db_engine, add_owner(db_engine))

    response = client.delete(f"/chats/{theirs}")

    assert response.status_code == 404, response.text
    assert "set-cookie" not in response.headers
    assert (count(db_engine, "guests"), count(db_engine, "chats")) == (0, 1)


@pytest.mark.usefixtures("fake_storage")
def test_citations_of_a_deleted_document_stay_in_other_chats_history(
    client: TestClient, db_engine: Engine, db_sessions: Sessions
) -> None:
    chat_a, doc = chat_with_doc(client, db_engine, db_sessions)
    chat_b = new_chat(client)
    add_answer(db_sessions, chat_a, doc)
    add_answer(db_sessions, chat_b, doc)

    assert client.delete(f"/documents/{doc}").status_code == 204

    answer = {"role": "assistant", "content": ANSWER, "citations": cited(doc)}
    assert history(client, chat_a) == [answer]
    assert history(client, chat_b) == [answer]


def test_client_disconnect_while_storing_the_answer_stores_no_partial_row(
    client: TestClient,
    db_engine: Engine,
    db_sessions: Sessions,
    streaming_replies: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    chat_id, _ = chat_with_doc(client, db_engine, db_sessions)
    streaming_replies('{"relevant": [0]}', " ".join(["word"] * 30))
    storing = asyncio.Event()
    insert = chats.insert_assistant_message

    async def stall_store(db: AsyncSession, chat: uuid.UUID, content: str, citations: Any) -> bool:
        storing.set()
        # The disconnect must cancel this wait; a store that finishes would send `done`.
        await asyncio.wait_for(asyncio.Event().wait(), timeout=10)
        return await insert(db, chat, content, citations)

    monkeypatch.setattr(chats, "insert_assistant_message", stall_store)

    body = post_then_disconnect(client, chat_id, gate=storing)

    assert storing.is_set()
    assert b"event: token" in body
    assert b"event: done" not in body
    assert b"event: error" not in body
    assert history(client, chat_id) == [user_message()]
    with db_engine.connect() as conn:
        idle = conn.execute(
            text(
                "SELECT count(*) FROM pg_stat_activity "
                "WHERE datname = current_database() AND state = 'idle in transaction'"
            )
        ).scalar_one()
    assert idle == 0
