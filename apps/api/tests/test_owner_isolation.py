"""Owner isolation (Security): one owner cannot read, change or cite another owner's data."""

import uuid

import pytest
from conftest import Objects, Sessions, axis, count, in_session
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.api.deps import GUEST_COOKIE
from app.repositories.chats import insert_assistant_message
from app.repositories.vector.chunks import replace_chunks
from app.schemas.chunks import EmbeddedChunk

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("fake_storage")]

FACT = "The zebra plan ships on Friday."
ANSWER = "It ships on Friday, per the zebra plan."


def test_another_owner_cannot_read_list_retry_delete_or_cite_my_data(
    client: TestClient, db_engine: Engine, db_sessions: Sessions, fake_storage: Objects
) -> None:
    # Owner A: a failed document with a chunk, and a chat whose answer cites that document.
    chat_a = client.post("/chats").json()["id"]
    token_a = client.cookies[GUEST_COOKIE]
    doc_a = client.post("/documents", files={"file": ("a.txt", b"mine", "text/plain")}).json()["id"]
    with db_engine.begin() as conn:
        conn.execute(
            text("UPDATE documents SET status = 'failed', error = 'boom' WHERE id = :id"),
            {"id": doc_a},
        )
    chunk = EmbeddedChunk(FACT, axis(0), {"source": "a.txt", "page": None})
    in_session(db_sessions, lambda db: replace_chunks(db, uuid.UUID(doc_a), [chunk]))
    citation = {"document_id": doc_a, "source": "a.txt", "page": None, "snippet": FACT}
    in_session(
        db_sessions,
        lambda db: insert_assistant_message(db, uuid.UUID(chat_a), ANSWER, [citation]),
    )

    # Owner B: its own guest, with nothing of its own yet.
    client.cookies.clear()
    chat_b = client.post("/chats").json()["id"]

    foreign = [
        client.get(f"/documents/{doc_a}"),
        client.post(f"/documents/{doc_a}/retry"),
        client.delete(f"/documents/{doc_a}"),
        client.get(f"/chats/{chat_a}/messages"),
        client.delete(f"/chats/{chat_a}"),
        client.post(f"/chats/{chat_a}/messages", json={"content": "where is it?"}),
    ]
    assert [r.status_code for r in foreign] == [404] * len(foreign)
    assert {r.json()["code"] for r in foreign} == {"not_found"}
    assert client.get("/documents").json() == []
    assert [chat["id"] for chat in client.get("/chats").json()] == [chat_b]

    # Owner A's data is unchanged by B's attempts.
    client.cookies.clear()
    client.cookies.set(GUEST_COOKIE, token_a)
    assert client.get(f"/documents/{doc_a}").json()["status"] == "failed"
    assert client.get(f"/chats/{chat_a}/messages").json() == [
        {"role": "assistant", "content": ANSWER, "citations": [citation]}
    ]
    assert (count(db_engine, "documents"), count(db_engine, "chunks")) == (1, 1)
    assert (count(db_engine, "chats"), count(db_engine, "messages")) == (2, 1)
    assert f"documents/{doc_a}" in fake_storage
