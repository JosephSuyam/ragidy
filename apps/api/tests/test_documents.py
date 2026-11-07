import uuid
from collections.abc import AsyncIterator, Callable, Iterator

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
        "detail": [
            {"type": "missing", "loc": ["body", "file"], "msg": "Field required", "input": None}
        ]
    }
    assert_nothing_written(response, db_engine, fake_storage)
