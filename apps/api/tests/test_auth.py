import asyncio
import uuid
from collections.abc import AsyncIterator, Callable
from dataclasses import asdict
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from argon2 import PasswordHasher
from conftest import (
    EMAIL,
    PASSWORD,
    after_barrier,
    app_client,
    concurrent_requests,
    count,
    leaking_tables,
    no_db,
    register,
    set_cookies,
    write,
)
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Engine, text

from app.api.deps import SESSION_COOKIE, current_owner
from app.core.config import Tier, get_settings
from app.core.errors import AppError
from app.repositories import users
from app.services import auth
from app.services.owners import CurrentOwner
from app.services.passwords import needs_rehash
from app.services.tokens import hash_token

GetDb = Callable[[], AsyncIterator[Any]]

BOB = "bob@example.com"
SESSION_TTL_S = 30 * 86400  # Settings.session_ttl_days default
EMAIL_TAKEN = {"code": "email_taken", "detail": "An account with this email already exists"}
INVALID = {"code": "invalid_credentials", "detail": "Wrong email or password"}
RATE_LIMITED = {"code": "rate_limited", "detail": "Too many requests; try again later"}


def register_raw(client: TestClient, email: str, password: str) -> Response:
    return client.post("/auth/register", json={"email": email, "password": password})


def login(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> Response:
    return client.post("/auth/login", json={"email": email, "password": password})


def seed_user(db_engine: Engine, email: str, password_hash: str | None) -> None:
    """A user inserted directly; a NULL password is an OAuth-only account."""
    with db_engine.begin() as conn:
        owner_id = conn.execute(
            text("INSERT INTO owners (kind) VALUES ('user') RETURNING id")
        ).scalar_one()
        conn.execute(
            text("INSERT INTO users (owner_id, email, password) VALUES (:o, :e, :p)"),
            {"o": owner_id, "e": email, "p": password_hash},
        )


def user_owner_id(db_engine: Engine, email: str = EMAIL) -> str:
    with db_engine.connect() as conn:
        owner_id = conn.execute(
            text("SELECT owner_id FROM users WHERE email = :e"), {"e": email}
        ).scalar_one()
    return str(owner_id)


def use_only_cookie(client: TestClient, name: str, value: str) -> None:
    client.cookies.clear()
    client.cookies.set(name, value)


@pytest.mark.integration
def test_register_creates_user_session_and_cookie(client: TestClient, db_engine: Engine) -> None:
    response = register(client)
    raw = response.cookies[SESSION_COOKIE]
    with db_engine.connect() as conn:
        user = conn.execute(text("SELECT id, password FROM users")).one()
        session = conn.execute(
            text("SELECT user_id, token, expires_at - created_at AS ttl FROM sessions")
        ).one()
        assert leaking_tables(conn, PASSWORD) == []
        assert leaking_tables(conn, raw) == []
    assert response.json() == {"id": str(user.id), "email": EMAIL}
    assert (session.user_id, session.token) == (user.id, hash_token(raw))
    assert session.ttl == timedelta(seconds=SESSION_TTL_S)
    assert user.password.startswith("$argon2id$")
    assert PasswordHasher().verify(user.password, PASSWORD)

    cookies = set_cookies(response)
    assert list(cookies) == [SESSION_COOKIE]  # no guest cookie was sent, so none is cleared
    morsel = cookies[SESSION_COOKIE]
    assert morsel["httponly"] is True
    assert morsel["samesite"] == "lax"
    assert morsel["path"] == "/"
    assert morsel["max-age"] == str(SESSION_TTL_S)
    assert not morsel["secure"]


@pytest.mark.integration
def test_register_normalizes_email(client: TestClient, db_engine: Engine) -> None:
    response = register(client, email="  Alice@EXAMPLE.com ")
    assert response.json()["email"] == EMAIL
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT email FROM users")).scalar_one() == EMAIL
    assert login(client, email=" ALICE@example.COM").status_code == 200


@pytest.mark.integration
@pytest.mark.parametrize("existing", ["password", "oauth_only"])
def test_register_existing_email_409(client: TestClient, db_engine: Engine, existing: str) -> None:
    if existing == "password":
        register(client)
        client.cookies.clear()
    else:
        seed_user(db_engine, EMAIL, None)

    response = register_raw(client, "Alice@Example.com", "another password")
    assert response.status_code == 409
    assert response.json() == EMAIL_TAKEN
    assert "set-cookie" not in response.headers
    with db_engine.connect() as conn:
        stored = conn.execute(text("SELECT password FROM users")).scalars().all()
    assert len(stored) == 1
    # An OAuth-only account must not gain a password from a stranger's registration.
    assert (stored[0] is None) == (existing == "oauth_only")


@pytest.mark.integration
def test_register_concurrent_duplicate_409(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client)
    client.cookies.clear()

    async def lost_race(db: Any, email: str) -> None:
        return None  # the other registration commits after this pre-check

    monkeypatch.setattr(users, "get_user_by_email", lost_race)
    response = register_raw(client, EMAIL, PASSWORD)
    assert response.status_code == 409
    assert response.json() == EMAIL_TAKEN
    assert "set-cookie" not in response.headers
    assert (count(db_engine, "users"), count(db_engine, "owners")) == (1, 1)


@pytest.mark.integration
def test_concurrent_registrations_same_email_one_user(
    db_override: GetDb, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Both pre-checks see no user before either inserts, so the unique email decides.
    monkeypatch.setattr(users, "get_user_by_email", after_barrier(users.get_user_by_email))

    async def send(client: httpx.AsyncClient) -> Response:
        return await client.post("/auth/register", json={"email": EMAIL, "password": PASSWORD})

    responses = concurrent_requests(db_override, send, send)

    assert sorted(r.status_code for r in responses) == [201, 409]
    loser = next(r for r in responses if r.status_code == 409)
    assert loser.json() == EMAIL_TAKEN
    assert "set-cookie" not in loser.headers
    assert (count(db_engine, "users"), count(db_engine, "owners")) == (1, 1)
    assert count(db_engine, "sessions") == 1


@pytest.mark.usefixtures("app_env")
@pytest.mark.parametrize(
    ("path", "password"),
    [("/auth/register", "a" * 7), ("/auth/register", "a" * 129), ("/auth/login", "a" * 129)],
)
def test_register_password_length_422(path: str, password: str) -> None:
    with app_client(no_db) as client:
        response = client.post(path, json={"email": EMAIL, "password": password})
    assert response.status_code == 422


@pytest.mark.integration
def test_login_rotates_incoming_session(client: TestClient, db_engine: Engine) -> None:
    old = register(client).cookies[SESSION_COOKIE]
    response = login(client)
    assert response.status_code == 200
    assert response.json()["email"] == EMAIL
    new = response.cookies[SESSION_COOKIE]
    with db_engine.connect() as conn:
        tokens = conn.execute(text("SELECT token FROM sessions")).scalars().all()
    assert new != old
    assert tokens == [hash_token(new)]

    use_only_cookie(client, SESSION_COOKIE, old)
    assert client.get("/me").json()["tier"] == "guest"


@pytest.mark.integration
@pytest.mark.parametrize(
    ("email", "password"),
    [
        (EMAIL, "wrong password"),
        ("nobody@example.com", PASSWORD),
        (BOB, PASSWORD),  # OAuth-only, no password
        ("not-an-email", PASSWORD),
    ],
)
def test_login_failures_same_401(
    client: TestClient, db_engine: Engine, email: str, password: str
) -> None:
    register(client)
    seed_user(db_engine, BOB, None)

    response = login(client, email, password)
    assert response.status_code == 401
    assert response.json() == INVALID
    assert "set-cookie" not in response.headers
    assert count(db_engine, "sessions") == 1  # the incoming session survives a failed login


@pytest.mark.integration
def test_login_rehashes_outdated_hash(client: TestClient, db_engine: Engine) -> None:
    old_hash = PasswordHasher(time_cost=1).hash(PASSWORD)
    assert needs_rehash(old_hash)
    seed_user(db_engine, EMAIL, old_hash)

    assert login(client).status_code == 200
    with db_engine.connect() as conn:
        stored = conn.execute(text("SELECT password FROM users")).scalar_one()
    assert stored != old_hash
    assert not needs_rehash(stored)
    assert PasswordHasher().verify(stored, PASSWORD)


@pytest.mark.integration
def test_login_failure_lockout_per_email_and_ip(
    db_override: GetDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "2")
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "100")
    with app_client(db_override) as client:
        register(client)
        register(client, BOB)
        assert [login(client, password="wrong").status_code for _ in range(2)] == [401, 401]

        blocked = login(client)  # each attempt reserves a slot first, so a correct one is 429
        assert blocked.status_code == 429
        assert blocked.json() == RATE_LIMITED
        window_s = get_settings().login_failure_window_minutes * 60
        assert 0 < int(blocked.headers["retry-after"]) <= window_s
        assert "set-cookie" not in blocked.headers

        # Another email from the same IP is not locked, and successes never count as failures.
        assert [login(client, BOB).status_code for _ in range(3)] == [200, 200, 200]

    with app_client(db_override, client=("203.0.113.9", 1)) as other_ip:
        assert login(other_ip).status_code == 200


@pytest.mark.integration
def test_login_success_clears_failures(db_override: GetDb, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "2")
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "100")
    with app_client(db_override) as client:
        register(client)
        assert login(client, password="wrong").status_code == 401
        assert login(client).status_code == 200
        assert [login(client, password="wrong").status_code for _ in range(2)] == [401, 401]


@pytest.mark.usefixtures("app_env")
def test_parallel_wrong_logins_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "3")
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "100")
    user = SimpleNamespace(password="$argon2id$stub")
    verifies = 0

    async def get_user(db: Any, email: str) -> Any:
        await asyncio.sleep(0)  # lets every attempt start before any verify finishes
        return user

    async def wrong_password(hash: str, pw: str) -> bool:
        nonlocal verifies
        verifies += 1
        await asyncio.sleep(0)
        return False

    class FakeDb:
        async def commit(self) -> None:
            await asyncio.sleep(0)

    monkeypatch.setattr(users, "get_user_by_email", get_user)
    monkeypatch.setattr(auth, "verify_password", wrong_password)

    async def burst() -> list[Any]:
        attempts = (
            auth.login(FakeDb(), EMAIL, "wrong", ip_key="ip", session_token=None, guest_token=None)
            for _ in range(10)
        )
        return await asyncio.gather(*attempts, return_exceptions=True)

    results = asyncio.run(burst(), loop_factory=asyncio.SelectorEventLoop)
    assert all(isinstance(error, AppError) for error in results)
    assert sorted(error.status for error in results) == [401] * 3 + [429] * 7
    assert verifies == 3


@pytest.mark.usefixtures("app_env")
def test_login_email_length_cap_422() -> None:
    with app_client(no_db) as client:
        too_long = login(client, "a" * 255)
        at_cap = login(client, "a" * 254)
    assert too_long.status_code == 422
    # 254 passes the schema, then fails email validation before any DB access.
    assert at_cap.status_code == 401


@pytest.mark.integration
@pytest.mark.parametrize("field", ["email", "password"])
def test_register_nul_422_stores_nothing(client: TestClient, db_engine: Engine, field: str) -> None:
    body = {"email": BOB, "password": PASSWORD}
    body[field] = f"{body[field]}\x00{uuid.uuid4().hex}"

    response = client.post("/auth/register", json=body)

    assert response.status_code == 422, response.text
    assert "set-cookie" not in response.headers
    assert (
        count(db_engine, "users"),
        count(db_engine, "owners"),
        count(db_engine, "sessions"),
    ) == (
        0,
        0,
        0,
    )


@pytest.mark.integration
@pytest.mark.parametrize("field", ["email", "password"])
def test_login_nul_422_consumes_no_failure_or_rate_slot(
    db_override: GetDb, db_engine: Engine, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    monkeypatch.setenv("LOGIN_MAX_FAILURES", "1")
    monkeypatch.setenv(
        "RATE_LIMIT_AUTH_PER_MINUTE", "2"
    )  # register takes one, valid login the other
    with app_client(db_override) as client:
        register(client)
        sessions_before = count(db_engine, "sessions")
        for _ in range(5):
            body = {"email": EMAIL, "password": PASSWORD}
            body[field] = f"{body[field]}\x00{uuid.uuid4().hex}"
            response = client.post("/auth/login", json=body)
            assert response.status_code == 422, response.text
            assert "set-cookie" not in response.headers
        assert count(db_engine, "sessions") == sessions_before

        valid = login(client)
    assert valid.status_code == 200, valid.text


@pytest.mark.integration
def test_register_display_name_email_logs_in(client: TestClient, db_engine: Engine) -> None:
    assert register(client, email="Alice <alice@example.com>").json()["email"] == EMAIL
    client.cookies.clear()
    assert login(client, email=EMAIL).status_code == 200


@pytest.mark.integration
def test_auth_rate_limit_429_retry_after(
    db_override: GetDb, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("RATE_LIMIT_AUTH_PER_MINUTE", "2")
    with app_client(db_override) as client:
        register(client)
        assert login(client, password="wrong").status_code == 401
        # Register and login share one per-IP budget.
        for response in (register_raw(client, BOB, PASSWORD), login(client)):
            assert response.status_code == 429
            assert response.json() == RATE_LIMITED
            assert 0 < int(response.headers["retry-after"]) <= 60
    assert count(db_engine, "users") == 1


@pytest.mark.integration
def test_logout_deletes_session_and_clears_cookie(client: TestClient, db_engine: Engine) -> None:
    raw = register(client).cookies[SESSION_COOKIE]
    response = client.post("/auth/logout")
    assert response.status_code == 204
    morsel = set_cookies(response)[SESSION_COOKIE]
    assert (morsel.value, morsel["max-age"], morsel["path"]) == ("", "0", "/")
    assert (morsel["httponly"], morsel["samesite"]) == (True, "lax")
    assert (count(db_engine, "sessions"), count(db_engine, "users")) == (0, 1)

    use_only_cookie(client, SESSION_COOKIE, raw)
    assert client.get("/me").json()["tier"] == "guest"


@pytest.mark.usefixtures("app_env")
def test_logout_without_session_204() -> None:
    with app_client(no_db) as client:
        response = client.post("/auth/logout")
    assert response.status_code == 204
    assert set_cookies(response)[SESSION_COOKIE]["max-age"] == "0"


@pytest.mark.integration
@pytest.mark.parametrize("cookie", ["unknown", "expired"])
def test_logout_with_unknown_or_expired_session_204(
    client: TestClient, db_engine: Engine, cookie: str
) -> None:
    alice = register(client).cookies[SESSION_COOKIE]
    client.cookies.clear()
    bob = register(client, BOB).cookies[SESSION_COOKIE]
    if cookie == "expired":
        with db_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE sessions SET expires_at = now() - interval '1 second' WHERE token = :t"
                ),
                {"t": hash_token(alice)},
            )
    use_only_cookie(client, SESSION_COOKIE, alice if cookie == "expired" else "no-such-token")

    response = client.post("/auth/logout")

    assert response.status_code == 204
    morsel = set_cookies(response)[SESSION_COOKIE]
    assert (morsel.value, morsel["max-age"]) == ("", "0")
    with db_engine.connect() as conn:
        tokens = set(conn.execute(text("SELECT token FROM sessions")).scalars())
    # An expired row is deleted like a live one; an unknown token deletes nothing.
    survivors = {hash_token(bob)} | ({hash_token(alice)} if cookie == "unknown" else set())
    assert tokens == survivors
    use_only_cookie(client, SESSION_COOKIE, bob)
    assert client.get("/me").json()["email"] == BOB


@pytest.mark.integration
def test_me_with_session_is_user_tier(client: TestClient) -> None:
    register(client)
    assert client.get("/me").json() == {
        "tier": "user",
        "email": EMAIL,
        "limits": asdict(get_settings().limits("user")),
        "document_count": 0,
        "guest_expires_at": None,
    }


@pytest.mark.integration
def test_session_cookie_wins_over_guest_cookie(client: TestClient, db_engine: Engine) -> None:
    session = register(client).cookies[SESSION_COOKIE]
    client.cookies.clear()
    guest_owner = write(client).json()["owner_id"]
    client.cookies.set(SESSION_COOKIE, session)

    me = client.get("/me").json()
    assert (me["tier"], me["email"]) == ("user", EMAIL)
    owner_id = write(client).json()["owner_id"]
    assert owner_id == user_owner_id(db_engine) != guest_owner


@pytest.mark.integration
def test_expired_session_is_no_session(client: TestClient, db_engine: Engine) -> None:
    register(client)
    with db_engine.begin() as conn:
        conn.execute(text("UPDATE sessions SET expires_at = now() - interval '1 second'"))

    me = client.get("/me").json()
    assert (me["tier"], me["email"]) == ("guest", None)
    assert write(client).json()["owner_id"] != user_owner_id(db_engine)
    assert count(db_engine, "guests") == 1


@pytest.mark.integration
@pytest.mark.parametrize("tier", ["user", "guest"])
def test_write_with_missing_owner_row_401_session_expired(
    client: TestClient, db_engine: Engine, tier: Tier
) -> None:
    from app.main import app

    # The owner resolved, then a purge or a guest migration deleted its row before the write.
    stale = CurrentOwner(uuid.uuid4(), tier, None, None)
    app.dependency_overrides[current_owner] = lambda: stale
    response = client.post("/_test/write")
    assert response.status_code == 401
    assert response.json() == {
        "code": "session_expired",
        "detail": "Your session expired; refresh and try again",
    }
    assert "set-cookie" not in response.headers
    assert count(db_engine, "owners") == 0
