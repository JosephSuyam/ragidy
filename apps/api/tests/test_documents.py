import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx
import pytest
from conftest import (
    NOTES_MD,
    Objects,
    after_barrier,
    app_client,
    concurrent_requests,
    count,
    register,
    set_cookies,
    write,
)
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import GUEST_COOKIE
from app.core import storage
from app.services import documents

pytestmark = pytest.mark.integration

GetDb = Callable[[], AsyncIterator[AsyncSession]]
MIB = 1024 * 1024
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"


def upload(
    client: TestClient, data: bytes, name: str = "notes.txt", content_type: str = "text/plain"
) -> Response:
    return client.post("/documents", files={"file": (name, data, content_type)})


def add_url(client: TestClient, url: str) -> Response:
    return client.post("/documents/url", json={"url": url})


def stored_documents(db_engine: Engine) -> dict[str, uuid.UUID]:
    """Each document's object key, mapped to its owner id."""
    with db_engine.connect() as conn:
        rows = conn.execute(text("SELECT id, owner_id FROM documents"))
        return {f"documents/{id}": owner_id for id, owner_id in rows}


def assert_nothing_written(response: Response, db_engine: Engine, objects: Objects) -> None:
    assert "set-cookie" not in response.headers
    assert objects == {}
    assert (count(db_engine, "documents"), count(db_engine, "guests")) == (0, 0)


def test_upload_stores_object_then_pending_row_for_new_guest(
    client: TestClient, db_engine: Engine, fake_storage: Objects
) -> None:
    response = upload(client, NOTES_MD, "notes/archive/notes.md", "application/octet-stream")

    assert response.status_code == 202, response.text
    body = response.json()
    assert {k: body[k] for k in ("source", "status", "error", "attempts")} == {
        "source": "notes.md",
        "status": "pending",
        "error": None,
        "attempts": 0,
    }
    key = f"documents/{body['id']}"
    assert fake_storage == {key: (NOTES_MD, "text/markdown")}
    assert GUEST_COOKIE in set_cookies(response)
    assert list(stored_documents(db_engine)) == [key]
    assert client.get("/me").json()["document_count"] == 1


def test_upload_filename_nul_is_stripped(
    client: TestClient, db_engine: Engine, fake_storage: Objects
) -> None:
    boundary = "ragidy-test-boundary"
    head = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="a\x00.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    ).encode()
    body = head + b"plain words" + f"\r\n--{boundary}--\r\n".encode()
    assert b"\x00" in body, "httpx files= would send %00 instead of a raw NUL"

    response = client.post(
        "/documents",
        content=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )

    assert response.status_code == 202, response.text
    assert response.json()["source"] == "a.txt"
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT source FROM documents")).scalars().all() == ["a.txt"]


@pytest.mark.parametrize(
    ("extra", "status"),
    [(0, 202), (1, 413), (64 * 1024, 413)],  # 64 KiB over: rejected by Content-Length alone
)
def test_upload_size_limit(
    db_override: GetDb,
    db_engine: Engine,
    fake_storage: Objects,
    monkeypatch: pytest.MonkeyPatch,
    extra: int,
    status: int,
) -> None:
    monkeypatch.setenv("UPLOAD_MAX_MB_GUEST", "1")
    with app_client(db_override) as client:
        response = upload(client, b"a" * (MIB + extra))

    assert response.status_code == status, response.text
    if status == 202:
        assert len(fake_storage) == 1
    else:
        assert response.json() == {"code": "too_large", "detail": "Files may be at most 1 MB"}
        assert_nothing_written(response, db_engine, fake_storage)


def test_upload_without_content_length_stops_at_the_limit(
    db_override: GetDb, db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UPLOAD_MAX_MB_GUEST", "1")
    boundary = "ragidy-test-boundary"
    head = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="file"; filename="big.txt"\r\n'
        "Content-Type: text/plain\r\n\r\n"
    ).encode()
    body = head + b"a" * (MIB + 32 * 1024) + f"\r\n--{boundary}--\r\n".encode()

    def chunks() -> Iterator[bytes]:
        for start in range(0, len(body), 64 * 1024):
            yield body[start : start + 64 * 1024]

    with app_client(db_override) as client:
        response = client.post(
            "/documents",
            content=chunks(),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )

    assert response.status_code == 413, response.text
    assert response.json()["code"] == "too_large"
    assert_nothing_written(response, db_engine, fake_storage)


def test_type_comes_from_bytes_not_the_content_type_header(
    client: TestClient, db_engine: Engine, fake_storage: Objects
) -> None:
    spoofed = upload(client, PNG, "image.txt", "text/plain")
    assert spoofed.status_code == 415, spoofed.text
    assert spoofed.json()["code"] == "unsupported_type"
    assert_nothing_written(spoofed, db_engine, fake_storage)

    empty = upload(client, b"", "empty.txt", "text/plain")
    assert empty.status_code == 415, empty.text
    assert empty.json()["code"] == "unsupported_type"
    assert_nothing_written(empty, db_engine, fake_storage)

    plain = upload(client, b"plain words", "scan.pdf", "application/pdf")
    assert plain.status_code == 202, plain.text
    assert list(fake_storage.values()) == [(b"plain words", "text/plain")]


@pytest.mark.usefixtures("allow_loopback")
def test_type_not_in_tier_list_415(
    db_override: GetDb,
    db_engine: Engine,
    fake_storage: Objects,
    monkeypatch: pytest.MonkeyPatch,
    http_server: str,
) -> None:
    monkeypatch.setenv("UPLOAD_TYPES_GUEST", "pdf")
    expected = {"code": "unsupported_type", "detail": "Unsupported file type; allowed: pdf"}
    with app_client(db_override) as client:
        for response in (upload(client, b"hello"), add_url(client, f"{http_server}/notes.md")):
            assert response.status_code == 415, response.text
            assert response.json() == expected
            assert_nothing_written(response, db_engine, fake_storage)


def test_at_cap_409_before_reading_or_fetching(
    db_override: GetDb, db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_DOCS_GUEST", "1")
    expected = {"code": "document_limit_reached", "detail": "You can keep at most 1 documents"}
    with app_client(db_override) as client:
        assert upload(client, b"first").status_code == 202
        # A blocked URL still gets 409: the cap is checked before the fetch.
        for response in (upload(client, b"second"), add_url(client, "file:///etc/passwd")):
            assert response.status_code == 409, response.text
            assert response.json() == expected
    assert len(fake_storage) == 1
    assert count(db_engine, "documents") == 1


def test_concurrent_uploads_never_exceed_the_cap(
    db_override: GetDb, db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAX_DOCS_GUEST", "2")
    with app_client(db_override) as client:
        assert upload(client, b"first").status_code == 202
        token = client.cookies[GUEST_COOKIE]
    # Both pass the pre-read cap check before either inserts; the owner row lock decides.
    monkeypatch.setattr(documents, "check_cap", after_barrier(documents.check_cap))

    async def send(c: httpx.AsyncClient) -> Response:
        c.cookies.set(GUEST_COOKIE, token)
        return await c.post("/documents", files={"file": ("a.txt", b"second", "text/plain")})

    responses = concurrent_requests(db_override, send, send)

    assert sorted(r.status_code for r in responses) == [202, 409]
    assert set(fake_storage) == set(stored_documents(db_engine))
    assert len(fake_storage) == 2


def test_upload_after_owner_row_deleted_401_and_object_removed(
    client: TestClient, db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    guest_owner = write(client).json()["owner_id"]
    put = storage.put_object

    async def put_then_migrate(key: str, data: bytes, content_type: str) -> None:
        await put(key, data, content_type)
        # A guest migration (or purge) deletes the owner row between the put and the lock.
        with db_engine.begin() as conn:
            conn.execute(text("DELETE FROM owners WHERE id = :g"), {"g": guest_owner})

    monkeypatch.setattr(storage, "put_object", put_then_migrate)
    response = upload(client, b"hello")

    assert response.status_code == 401, response.text
    assert response.json()["code"] == "session_expired"
    assert fake_storage == {}
    assert count(db_engine, "documents") == 0


def test_failed_guest_creation_after_put_leaves_no_guest_or_object(
    db_override: GetDb, db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GUEST_CREATE_PER_IP_PER_HOUR", "1")
    with app_client(db_override) as client:
        assert upload(client, b"first").status_code == 202
        client.cookies.clear()
        response = upload(client, b"second")  # needs a second guest from the same IP

    assert response.status_code == 429, response.text
    assert "set-cookie" not in response.headers
    assert len(fake_storage) == 1
    assert (count(db_engine, "documents"), count(db_engine, "guests")) == (1, 1)


def test_signed_in_user_upload_uses_user_limits(
    db_override: GetDb, db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("UPLOAD_MAX_MB_GUEST", "1")
    monkeypatch.setenv("UPLOAD_MAX_MB_USER", "2")
    with app_client(db_override) as client:
        register(client)
        response = upload(client, b"a" * (MIB + 1))

    assert response.status_code == 202, response.text
    assert GUEST_COOKIE not in set_cookies(response)
    with db_engine.connect() as conn:
        user_owner = conn.execute(text("SELECT owner_id FROM users")).scalar_one()
    assert list(stored_documents(db_engine).values()) == [user_owner]
    assert count(db_engine, "guests") == 0


@pytest.mark.usefixtures("allow_loopback")
def test_add_url_stores_fetched_body(
    client: TestClient, db_engine: Engine, fake_storage: Objects, http_server: str
) -> None:
    url = f"{http_server}/to?url=/notes.md"  # the final URL's path decides md over txt

    response = add_url(client, url)

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["source"], body["status"]) == (url, "pending")
    assert fake_storage == {f"documents/{body['id']}": (NOTES_MD, "text/markdown")}
    assert GUEST_COOKIE in set_cookies(response)
    assert count(db_engine, "documents") == 1


def test_add_url_blocked_writes_nothing(
    client: TestClient, db_engine: Engine, fake_storage: Objects
) -> None:
    response = add_url(client, "http://169.254.169.254/latest/meta-data/")
    assert response.status_code == 422, response.text
    assert response.json()["code"] == "url_blocked"
    assert_nothing_written(response, db_engine, fake_storage)


def test_add_url_rate_limit_counts_every_attempt(
    db_override: GetDb, db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("URL_FETCH_PER_HOUR", "2")
    blocked_url = "file:///etc/passwd"  # fails without network, so only the limit can say 429
    with app_client(db_override) as client:
        assert [add_url(client, blocked_url).status_code for _ in range(2)] == [422, 422]

        limited = add_url(client, blocked_url)
        assert limited.status_code == 429, limited.text
        assert limited.json()["code"] == "rate_limited"
        assert 0 < int(limited.headers["retry-after"]) <= 3600
        assert "set-cookie" not in limited.headers

        # A signed-in owner has its own budget, keyed by owner id rather than client IP.
        register(client)
        assert add_url(client, blocked_url).status_code == 422
    assert fake_storage == {}
    assert count(db_engine, "documents") == 0


def test_upload_without_file_field_422(
    client: TestClient, db_engine: Engine, fake_storage: Objects
) -> None:
    response = client.post("/documents", files={"other": ("a.txt", b"x", "text/plain")})
    assert response.status_code == 422, response.text
    assert response.json() == {
        "detail": [{"type": "missing", "loc": ["body", "file"], "msg": "Field required"}]
    }
    assert_nothing_written(response, db_engine, fake_storage)


def test_add_url_nul_422_never_fetches(
    db_override: GetDb, db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("URL_FETCH_PER_HOUR", "1")
    fetched: list[str] = []
    real_fetch = documents.fetch_url

    async def spy(url: str, max_bytes: int) -> tuple[bytes, str]:
        fetched.append(url)
        return await real_fetch(url, max_bytes)

    monkeypatch.setattr(documents, "fetch_url", spy)
    nul_url = f"https://example.com/{uuid.uuid4().hex}\x00"
    with app_client(db_override) as client:
        nul_responses = [add_url(client, nul_url), add_url(client, nul_url)]
        # The limit of 1 is still free: only a 422 that skipped the limit leaves it open.
        blocked = add_url(client, "file:///etc/passwd")

    assert [r.status_code for r in nul_responses] == [422, 422]
    assert all("set-cookie" not in r.headers for r in nul_responses)
    assert (blocked.status_code, blocked.json()["code"]) == (422, "url_blocked")
    assert fetched == ["file:///etc/passwd"]
    assert fake_storage == {}
    assert count(db_engine, "documents") == 0


def set_status(db_engine: Engine, id: str, status: str, created_ago: int = 0) -> None:
    sql = (
        "UPDATE documents SET status = :status, attempts = 3, error = 'boom', "
        "created_at = now() - make_interval(secs => :ago) WHERE id = :id"
    )
    with db_engine.begin() as conn:
        conn.execute(text(sql), {"status": status, "ago": created_ago, "id": id})


def document_state(db_engine: Engine, id: str) -> tuple[Any, ...]:
    sql = "SELECT status, attempts, error FROM documents WHERE id = :id"
    with db_engine.connect() as conn:
        return tuple(conn.execute(text(sql), {"id": id}).one())


def new_guest_document(client: TestClient, status: str = "pending") -> tuple[str, str]:
    """Upload as a fresh guest; return the document id and the guest cookie."""
    client.cookies.clear()
    response = upload(client, b"hello")
    assert response.status_code == 202, response.text
    return response.json()["id"], client.cookies[GUEST_COOKIE]


def as_guest(client: TestClient, token: str) -> None:
    client.cookies.clear()
    client.cookies.set(GUEST_COOKIE, token)


@pytest.mark.usefixtures("fake_storage")
def test_list_documents_is_the_owners_newest_first(client: TestClient, db_engine: Engine) -> None:
    theirs, _ = new_guest_document(client)
    old, _ = new_guest_document(client)
    set_status(db_engine, old, "ready", created_ago=60)
    new = upload(client, b"second").json()["id"]

    response = client.get("/documents")

    assert response.status_code == 200, response.text
    assert [d["id"] for d in response.json()] == [new, old]
    assert theirs not in {d["id"] for d in response.json()}


def test_reads_without_a_cookie_find_nothing_and_create_no_guest(
    client: TestClient, db_engine: Engine
) -> None:
    listed = client.get("/documents")
    missing = client.get(f"/documents/{uuid.uuid4()}")

    assert (listed.status_code, listed.json()) == (200, [])
    assert missing.status_code == 404, missing.text
    for response in (listed, missing):
        assert "set-cookie" not in response.headers
    assert (count(db_engine, "owners"), count(db_engine, "guests")) == (0, 0)


@pytest.mark.usefixtures("fake_storage")
def test_get_document_is_owner_scoped(client: TestClient) -> None:
    theirs, _ = new_guest_document(client)
    mine, token = new_guest_document(client)
    as_guest(client, token)

    found = client.get(f"/documents/{mine}")
    assert found.status_code == 200, found.text
    assert {k: found.json()[k] for k in ("id", "status")} == {"id": mine, "status": "pending"}
    for id in (theirs, uuid.uuid4()):
        response = client.get(f"/documents/{id}")
        assert response.status_code == 404, response.text
        assert response.json() == {"code": "not_found", "detail": "Document not found"}


@pytest.mark.parametrize("status", ["failed", "ready"])
@pytest.mark.usefixtures("fake_storage")
def test_retry_requeues_a_finished_document(
    client: TestClient, db_engine: Engine, status: str
) -> None:
    id, _ = new_guest_document(client)
    set_status(db_engine, id, status)

    response = client.post(f"/documents/{id}/retry")

    assert response.status_code == 202, response.text
    body = response.json()
    assert (body["id"], body["status"], body["attempts"], body["error"]) == (id, "pending", 0, None)
    assert document_state(db_engine, id) == ("pending", 0, None)


@pytest.mark.parametrize("status", ["pending", "processing"])
@pytest.mark.usefixtures("fake_storage")
def test_retry_of_an_active_document_409(
    client: TestClient, db_engine: Engine, status: str
) -> None:
    id, _ = new_guest_document(client)
    set_status(db_engine, id, status)

    response = client.post(f"/documents/{id}/retry")

    assert response.status_code == 409, response.text
    assert response.json()["code"] == "document_busy"
    assert document_state(db_engine, id) == (status, 3, "boom")


@pytest.mark.usefixtures("fake_storage")
def test_retry_of_another_owners_or_without_a_cookie_404(
    client: TestClient, db_engine: Engine
) -> None:
    theirs, _ = new_guest_document(client)
    set_status(db_engine, theirs, "failed")
    _, token = new_guest_document(client)
    as_guest(client, token)
    guests = count(db_engine, "guests")

    foreign = client.post(f"/documents/{theirs}/retry")
    client.cookies.clear()
    anonymous = client.post(f"/documents/{theirs}/retry")

    for response in (foreign, anonymous):
        assert response.status_code == 404, response.text
        assert response.json()["code"] == "not_found"
    assert "set-cookie" not in anonymous.headers
    assert count(db_engine, "guests") == guests
    assert document_state(db_engine, theirs) == ("failed", 3, "boom")


def test_retry_rate_limit_counts_every_attempt(
    db_override: GetDb, db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DOCUMENT_RETRY_PER_HOUR", "2")
    with app_client(db_override) as client:
        id, _ = new_guest_document(client)
        set_status(db_engine, id, "failed")
        # The second attempt is refused as busy, yet still counts.
        statuses = [client.post(f"/documents/{id}/retry").status_code for _ in range(2)]
        limited = client.post(f"/documents/{id}/retry")

    assert statuses == [202, 409]
    assert limited.status_code == 429, limited.text
    assert limited.json()["code"] == "rate_limited"
    assert 0 < int(limited.headers["retry-after"]) <= 3600


@pytest.mark.usefixtures("fake_storage")
def test_retry_from_another_origin_403(client: TestClient, db_engine: Engine) -> None:
    id, _ = new_guest_document(client)
    set_status(db_engine, id, "failed")

    response = client.post(f"/documents/{id}/retry", headers={"Origin": "https://evil.example"})

    assert response.status_code == 403, response.text
    assert response.json()["code"] == "origin_mismatch"
    assert document_state(db_engine, id) == ("failed", 3, "boom")
