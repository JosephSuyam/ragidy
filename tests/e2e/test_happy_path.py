"""Upload a document, ask about it, read the answer back, then delete what was created."""

import json
import time
from collections.abc import Iterable, Iterator
from typing import Any

import httpx
import pytest

READY_TIMEOUT_S = 60
POLL_INTERVAL_S = 1
DOCUMENT = b"Uploads are stored in object storage.\n"
QUESTION = "Where are uploads stored?"


def _wait_ready(client: httpx.Client, doc_id: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_S
    while True:
        doc = client.get(f"/api/documents/{doc_id}").json()
        if doc["status"] == "ready":
            return
        if doc["status"] == "failed":
            pytest.fail(f"ingestion failed: {doc['error']}")
        if time.monotonic() > deadline:
            pytest.fail(f"document still {doc['status']} after {READY_TIMEOUT_S}s")
        time.sleep(POLL_INTERVAL_S)


def _parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, Any]]:
    event = "message"
    data: list[str] = []
    for line in lines:
        if not line:
            if data:
                yield event, json.loads("\n".join(data))
            event = "message"
            data = []
        elif line.startswith("event:"):
            event = line.removeprefix("event:").strip()
        elif line.startswith("data:"):
            data.append(line.removeprefix("data:").strip())


def _ask(client: httpx.Client, chat_id: str, content: str) -> list[tuple[str, Any]]:
    with client.stream(
        "POST", f"/api/chats/{chat_id}/messages", json={"content": content}
    ) as response:
        assert response.status_code == 200, response.read()
        return list(_parse_sse(response.iter_lines()))


def test_upload_ask_and_delete(client: httpx.Client) -> None:
    upload = client.post("/api/documents", files={"file": ("e2e.txt", DOCUMENT, "text/plain")})
    assert upload.status_code == 202, upload.text
    doc_id = upload.json()["id"]
    try:
        _wait_ready(client, doc_id)
        chat = client.post("/api/chats")
        assert chat.status_code == 201, chat.text
        chat_id = chat.json()["id"]
        try:
            events = _ask(client, chat_id, QUESTION)
            names = [name for name, _ in events]
            assert names[-1] == "done", events
            assert "token" in names
            citations = dict(events)["citations"]
            assert [c["document_id"] for c in citations] == [doc_id]

            messages = client.get(f"/api/chats/{chat_id}/messages").json()
            assistant = [m for m in messages if m["role"] == "assistant"]
            assert len(assistant) == 1
            streamed = "".join(data["text"] for name, data in events if name == "token")
            assert assistant[0]["content"] == streamed
            assert [c["document_id"] for c in assistant[0]["citations"]] == [doc_id]
        finally:
            assert client.delete(f"/api/chats/{chat_id}").status_code == 204
    finally:
        assert client.delete(f"/api/documents/{doc_id}").status_code == 204
