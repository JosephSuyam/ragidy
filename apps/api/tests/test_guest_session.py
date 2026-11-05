import hashlib
from datetime import datetime, timedelta
from http.cookies import SimpleCookie

import pytest
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, inspect, text

from app.api.deps import GUEST_COOKIE
from app.services.tokens import new_token

pytestmark = pytest.mark.integration

TTL_DAYS = 7  # Settings.guest_ttl_days default


def write(client: TestClient) -> Response:
    response = client.post("/_test/write")
    assert response.status_code == 200, response.text
    return response


def guest_cookie(response: Response) -> str:
    return response.cookies[GUEST_COOKIE]


def count(db_engine: Engine, table: str) -> int:
    with db_engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def test_first_write_creates_guest_and_sets_cookie(client: TestClient, db_engine: Engine) -> None:
    response = write(client)
    with db_engine.connect() as conn:
        guest = conn.execute(text("SELECT owner_id FROM guests")).one()
        kind = conn.execute(
            text("SELECT kind FROM owners WHERE id = :id"), {"id": guest.owner_id}
        ).scalar_one()
    assert response.json() == {"owner_id": str(guest.owner_id)}
    assert (count(db_engine, "guests"), kind) == (1, "guest")
    morsel = SimpleCookie(response.headers["set-cookie"])[GUEST_COOKIE]
    assert morsel["httponly"] is True
    assert morsel["samesite"] == "lax"
    assert morsel["path"] == "/"
    assert morsel["max-age"] == str(TTL_DAYS * 86400)
    assert not morsel["secure"]


def test_cookie_secure_on_https_base_url(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://app.example.com")
    morsel = SimpleCookie(write(client).headers["set-cookie"])[GUEST_COOKIE]
    assert morsel["secure"] is True


def test_guest_expires_at_is_created_plus_ttl(client: TestClient, db_engine: Engine) -> None:
    write(client)
    with db_engine.connect() as conn:
        ttl = conn.execute(text("SELECT expires_at - created_at FROM guests")).scalar_one()
    assert ttl == timedelta(days=TTL_DAYS)


def test_guest_row_stores_only_token_hash(client: TestClient, db_engine: Engine) -> None:
    raw = guest_cookie(write(client))
    with db_engine.connect() as conn:
        stored = conn.execute(text("SELECT token FROM guests")).scalar_one()
        assert stored == hashlib.sha256(raw.encode()).digest()
        for table in inspect(conn).get_table_names():
            # Row-to-text: the raw token, or its bytes as bytea hex, in any column.
            leaks = conn.execute(
                text(
                    f"SELECT count(*) FROM {table} t WHERE strpos(t::text, :raw) > 0 "
                    "OR strpos(t::text, :hex) > 0"
                ),
                {"raw": raw, "hex": raw.encode().hex()},
            ).scalar_one()
            assert leaks == 0, table


@pytest.mark.parametrize("cookie_kind", ["unknown", "expired"])
def test_unknown_or_expired_guest_cookie_is_no_cookie(
    client: TestClient, db_engine: Engine, cookie_kind: str
) -> None:
    if cookie_kind == "unknown":
        cookie, old_owner = new_token(), None
    else:
        response = write(client)
        cookie, old_owner = guest_cookie(response), response.json()["owner_id"]
        with db_engine.begin() as conn:
            conn.execute(text("UPDATE guests SET expires_at = now() - interval '1 second'"))
    client.cookies.clear()
    client.cookies.set(GUEST_COOKIE, cookie)

    me = client.get("/me").json()
    assert (me["guest_expires_at"], me["document_count"]) == (None, 0)

    response = write(client)
    assert guest_cookie(response) != cookie
    assert response.json()["owner_id"] != old_owner
    assert count(db_engine, "guests") == (1 if old_owner is None else 2)


def test_me_with_guest_cookie_reports_expiry_and_document_count(
    client: TestClient, db_engine: Engine
) -> None:
    owner_id = write(client).json()["owner_id"]
    with db_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO documents (owner_id, source, embed_model) "
                "VALUES (:o, 'a.pdf', 'm'), (:o, 'b.pdf', 'm')"
            ),
            {"o": owner_id},
        )
        expires_at = conn.execute(text("SELECT expires_at FROM guests")).scalar_one()

    me = client.get("/me").json()
    assert (me["tier"], me["email"], me["document_count"]) == ("guest", None, 2)
    assert datetime.fromisoformat(me["guest_expires_at"]) == expires_at


def test_second_write_reuses_guest(client: TestClient, db_engine: Engine) -> None:
    first = write(client)
    second = write(client)
    assert second.json() == first.json()
    assert "set-cookie" not in second.headers
    assert count(db_engine, "guests") == 1


def test_guest_creation_over_limit_returns_429_and_creates_no_guest(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("GUEST_CREATE_PER_IP_PER_HOUR", "2")
    for _ in range(2):
        write(client)
        client.cookies.clear()

    response = client.post("/_test/write")
    assert response.status_code == 429
    assert response.json() == {
        "code": "rate_limited",
        "detail": "Too many guest sessions from this address; try again later",
    }
    assert 0 < int(response.headers["retry-after"]) <= 3600
    assert "set-cookie" not in response.headers
    assert count(db_engine, "guests") == 2


def test_failed_write_leaves_no_guest_and_no_cookie(client: TestClient, db_engine: Engine) -> None:
    response = client.post("/_test/write_fail")
    assert response.status_code == 409
    assert response.json() == {"code": "x", "detail": "y"}
    assert "set-cookie" not in response.headers
    assert (count(db_engine, "guests"), count(db_engine, "owners")) == (0, 0)
