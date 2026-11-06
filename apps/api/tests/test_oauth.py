import base64
import hashlib
import logging
import time
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from conftest import (
    EMAIL,
    ORIGIN,
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
from pydantic import SecretStr
from sqlalchemy import Engine, text

from app.api.deps import GUEST_COOKIE, OAUTH_COOKIE, SESSION_COOKIE
from app.core.config import get_settings
from app.core.oauth import PROVIDERS, Identity, OAuthProvider, enabled
from app.repositories import users
from app.services import oauth
from app.services.tokens import hash_token, sign, unsign

pytestmark = pytest.mark.usefixtures("oauth_env")

SECRET = "auth-secret-" + "s" * 32
GITHUB_SECRET = "github-client-secret-5d1e"
GOOGLE_SECRET = "google-client-secret-8e2f"
CODE = "provider-code-7f3a9b"
ACCESS_TOKEN = "provider-access-token-91c2"
STATE = "fixed-state-4b7d"
BOB = "bob@example.com"
SESSION_TTL_S = 30 * 86400  # Settings.session_ttl_days default
SUCCESS = f"{ORIGIN}/"
FAILED = f"{ORIGIN}/login?error=oauth_failed"
GITHUB, GOOGLE = PROVIDERS["github"], PROVIDERS["google"]
TOKEN_REPLY = {"access_token": ACCESS_TOKEN, "token_type": "bearer"}


@pytest.fixture
def oauth_env(app_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    # After app_env, because clean_env deletes every Settings variable.
    monkeypatch.setenv("AUTH_SECRET", SECRET)
    monkeypatch.setenv("OAUTH_GITHUB_CLIENT_ID", "github-id")
    monkeypatch.setenv("OAUTH_GITHUB_CLIENT_SECRET", GITHUB_SECRET)
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_ID", "google-id")
    monkeypatch.setenv("OAUTH_GOOGLE_CLIENT_SECRET", GOOGLE_SECRET)
    get_settings.cache_clear()


def disable(monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    monkeypatch.delenv(f"OAUTH_{provider.upper()}_CLIENT_ID")
    monkeypatch.delenv(f"OAUTH_{provider.upper()}_CLIENT_SECRET")
    get_settings.cache_clear()


def provider_http(
    monkeypatch: pytest.MonkeyPatch,
    replies: dict[str, Any],
    seen: list[httpx.Request] | None = None,
) -> None:
    """Fake the provider: each URL answers its JSON body or `httpx.Response`, or raises
    its `httpx.TransportError` class; other URLs fail the test."""

    def handler(request: httpx.Request) -> httpx.Response:
        # AssertionError, not KeyError: the service turns KeyError into provider_failed.
        assert str(request.url) in replies, f"unexpected provider call: {request.url}"
        if seen is not None:
            seen.append(request)
        reply = replies[str(request.url)]
        if isinstance(reply, type) and issubclass(reply, httpx.TransportError):
            raise reply("provider unreachable", request=request)
        return reply if isinstance(reply, httpx.Response) else httpx.Response(200, json=reply)

    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(oauth, "_http", lambda: httpx.AsyncClient(transport=transport))


def github_http(
    monkeypatch: pytest.MonkeyPatch,
    uid: int = 7,
    email: str = EMAIL,
    verified: bool = True,
    seen: list[httpx.Request] | None = None,
) -> None:
    emails = [
        {"email": "other@example.com", "primary": False, "verified": True},
        {"email": email, "primary": True, "verified": verified},
    ]
    provider_http(
        monkeypatch,
        {
            GITHUB.token_url: TOKEN_REPLY,
            GITHUB.identity_urls[0]: {"id": uid, "login": "alice"},
            GITHUB.identity_urls[1]: emails,
        },
        seen,
    )


def google_http(
    monkeypatch: pytest.MonkeyPatch,
    sub: str = "g-1",
    email: str = EMAIL,
    verified: bool = True,
    seen: list[httpx.Request] | None = None,
) -> None:
    info = {"sub": sub, "email": email, "email_verified": verified}
    provider_http(monkeypatch, {GOOGLE.token_url: TOKEN_REPLY, GOOGLE.identity_urls[0]: info}, seen)


def authorize(client: TestClient, provider: str = "github") -> tuple[str, dict[str, str]]:
    """GET start; the authorize URL without its query, and the query."""
    response = client.get(f"/auth/oauth/{provider}/start", follow_redirects=False)
    assert response.status_code == 302, response.text
    url = urlsplit(response.headers["location"])
    query = {key: values[0] for key, values in parse_qs(url.query, strict_parsing=True).items()}
    return f"{url.scheme}://{url.netloc}{url.path}", query


def callback(client: TestClient, provider: str = "github", **params: str) -> Response:
    return client.get(f"/auth/oauth/{provider}/callback", params=params, follow_redirects=False)


def sign_in(client: TestClient, provider: str = "github") -> str:
    """A full successful sign-in; the raw session token."""
    state = authorize(client, provider)[1]["state"]
    response = callback(client, provider, code=CODE, state=state)
    assert (response.status_code, response.headers["location"]) == (302, SUCCESS)
    session = set_cookies(response)[SESSION_COOKIE]
    assert session.value
    return session.value


def assert_cleared(response: Response, name: str) -> None:
    cleared = set_cookies(response)[name]
    assert (cleared.value, cleared["max-age"]) == ("", "0")


def assert_failed(response: Response) -> None:
    assert (response.status_code, response.headers["location"]) == (302, FAILED)
    assert_cleared(response, OAUTH_COOKIE)
    assert SESSION_COOKIE not in set_cookies(response)


def oauth_cookie(**overrides: Any) -> str:
    payload = {"state": STATE, "verifier": "v" * 43, "provider": "github"} | overrides
    return sign({"exp": int(time.time()) + 600} | payload, SECRET)


def session_hashes(db_engine: Engine) -> set[bytes]:
    with db_engine.connect() as conn:
        return set(conn.execute(text("SELECT token FROM sessions")).scalars())


def oauth_warnings(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records if r.name == oauth.logger.name]


@pytest.mark.parametrize(
    ("enabled", "expected"),
    [
        ([], []),
        (["github"], [{"id": "github", "name": "GitHub"}]),
        (
            ["google", "github"],
            [{"id": "google", "name": "Google"}, {"id": "github", "name": "GitHub"}],
        ),
    ],
)
def test_providers_lists_enabled_only(
    monkeypatch: pytest.MonkeyPatch, enabled: list[str], expected: list[dict[str, str]]
) -> None:
    for provider in {"google", "github"} - set(enabled):
        disable(monkeypatch, provider)
    with app_client(no_db) as client:
        response = client.get("/auth/providers")
    assert response.status_code == 200
    assert response.json() == expected


def test_start_redirects_with_state_and_s256() -> None:
    with app_client(no_db) as client:
        response = client.get("/auth/oauth/github/start", follow_redirects=False)
        _, other = authorize(client)
    assert response.status_code == 302
    url = urlsplit(response.headers["location"])
    assert f"{url.scheme}://{url.netloc}{url.path}" == GITHUB.authorize_url
    query = {key: values[0] for key, values in parse_qs(url.query, strict_parsing=True).items()}
    assert query == {
        "response_type": "code",
        "client_id": "github-id",
        "redirect_uri": f"{ORIGIN}/api/auth/oauth/github/callback",
        "scope": GITHUB.scopes,
        "state": query["state"],
        "code_challenge": query["code_challenge"],
        "code_challenge_method": "S256",
    }

    cookie = set_cookies(response)[OAUTH_COOKIE]
    assert (cookie["max-age"], cookie["path"], cookie["samesite"].lower()) == ("600", "/", "lax")
    assert cookie["httponly"] is True
    payload = unsign(cookie.value, SECRET)
    assert payload is not None
    assert (payload["state"], payload["provider"]) == (query["state"], "github")
    digest = hashlib.sha256(payload["verifier"].encode()).digest()
    assert query["code_challenge"] == base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    assert time.time() + 590 < payload["exp"] <= time.time() + 600
    assert len(payload["verifier"]) >= 43  # RFC 7636 minimum
    assert other["state"] != query["state"]
    assert other["code_challenge"] != query["code_challenge"]


@pytest.mark.parametrize("provider", ["nope", "google"])
def test_start_unknown_provider_404(monkeypatch: pytest.MonkeyPatch, provider: str) -> None:
    disable(monkeypatch, "google")
    with app_client(no_db) as client:
        response = client.get(f"/auth/oauth/{provider}/start", follow_redirects=False)
    assert response.status_code == 404
    assert response.json()["code"] == "not_found"
    assert OAUTH_COOKIE not in set_cookies(response)


FULL = {"code": CODE, "state": STATE}
NO_CALLS: dict[str, Any] = {}
# Cookies are built in the test body, so a slow collection cannot expire them.


@pytest.mark.parametrize(
    ("provider", "cookie", "params", "replies", "reason"),
    [
        pytest.param("github", None, FULL, NO_CALLS, "bad_request", id="no_cookie"),
        pytest.param(
            "github", lambda: oauth_cookie() + "x", FULL, NO_CALLS, "bad_request", id="tampered"
        ),
        pytest.param(
            "github",
            lambda: oauth_cookie(exp=int(time.time()) - 1),
            FULL,
            NO_CALLS,
            "bad_request",
            id="expired",
        ),
        pytest.param(
            "github",
            oauth_cookie,
            {"code": CODE, "state": "other"},
            NO_CALLS,
            "state_mismatch",
            id="state_mismatch",
        ),
        pytest.param(
            "github",
            lambda: oauth_cookie(provider="google"),
            FULL,
            NO_CALLS,
            "bad_cookie",
            id="provider_mismatch",
        ),
        pytest.param(
            "nope",
            lambda: oauth_cookie(provider="nope"),
            FULL,
            NO_CALLS,
            "bad_request",
            id="unknown_provider",
        ),
        pytest.param(
            "github", oauth_cookie, {"state": STATE}, NO_CALLS, "bad_request", id="no_code"
        ),
        pytest.param(
            "github",
            oauth_cookie,
            FULL | {"error": "access_denied"},
            NO_CALLS,
            "bad_request",
            id="access_denied",
        ),
        pytest.param(
            "github",
            oauth_cookie,
            FULL,
            {GITHUB.token_url: httpx.Response(500)},
            "provider_failed:HTTPStatusError",
            id="token_500",
        ),
        pytest.param(
            "github",
            oauth_cookie,
            FULL,
            {GITHUB.token_url: {"error": "bad_verification_code"}},
            "provider_failed:ValueError",
            id="no_access_token",
        ),
    ],
)
def test_callback_bad_cookie_or_state_or_provider_error_redirects_oauth_failed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    provider: str,
    cookie: Callable[[], str] | None,
    params: dict[str, str],
    replies: dict[str, Any],
    reason: str,
) -> None:
    provider_http(monkeypatch, replies)
    # no_db: any DB access fails the test, so a failed callback writes no rows.
    with app_client(no_db) as client:
        if cookie is not None:
            client.cookies.set(OAUTH_COOKIE, cookie())
        response = callback(client, provider, **params)
    assert_failed(response)
    assert oauth_warnings(caplog) == [f"oauth callback failed: {reason}"]


def assert_provider_failed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    provider: str,
    replies: dict[str, Any],
    reason: str,
) -> None:
    """A callback with a valid cookie and state fails with `reason` and touches no DB."""
    caplog.set_level(logging.DEBUG)
    provider_http(monkeypatch, replies)
    with app_client(no_db) as client:
        client.cookies.set(OAUTH_COOKIE, oauth_cookie(provider=provider))
        response = callback(client, provider, **FULL)
    assert_failed(response)
    assert oauth_warnings(caplog) == [f"oauth callback failed: {reason}"]


@pytest.mark.parametrize("error", [httpx.ConnectTimeout, httpx.ConnectError])
@pytest.mark.parametrize("failing", ["token", "identity"])
def test_callback_provider_timeout_redirects_oauth_failed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    error: type[httpx.TransportError],
    failing: str,
) -> None:
    url = GITHUB.token_url if failing == "token" else GITHUB.identity_urls[0]
    replies = {GITHUB.token_url: TOKEN_REPLY, url: error}
    assert_provider_failed(
        monkeypatch, caplog, "github", replies, f"provider_failed:{error.__name__}"
    )


MARKER = "provider-body-marker-3c9e"
NOT_JSON = httpx.Response(200, text=f"<html>{MARKER}</html>")


@pytest.mark.parametrize(
    ("provider", "identity", "reason"),
    [
        pytest.param("google", [{"email": MARKER}], "KeyError", id="google_no_sub"),
        pytest.param("google", [[MARKER]], "TypeError", id="google_list"),
        pytest.param("google", [NOT_JSON], "JSONDecodeError", id="google_not_json"),
        pytest.param(
            "google",
            [{"sub": None, "email": MARKER, "email_verified": True}],
            "ValueError",
            id="google_null_sub",
        ),
        pytest.param(
            "github",
            [{"login": MARKER}, [{"email": EMAIL, "primary": True, "verified": True}]],
            "KeyError",
            id="github_user_no_id",
        ),
        pytest.param(
            "github", [{"id": 7}, {"message": MARKER}], "AttributeError", id="github_emails_dict"
        ),
        pytest.param("github", [{"id": 7}, 42], "TypeError", id="github_emails_number"),
        pytest.param(
            "github", [{"id": 7}, [MARKER, None]], "AttributeError", id="github_email_not_dict"
        ),
    ],
)
def test_callback_malformed_identity_redirects_oauth_failed(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    provider: str,
    identity: list[Any],
    reason: str,
) -> None:
    entry = PROVIDERS[provider]
    replies = {entry.token_url: TOKEN_REPLY} | dict(zip(entry.identity_urls, identity, strict=True))
    assert_provider_failed(monkeypatch, caplog, provider, replies, f"provider_failed:{reason}")
    assert not [r for r in caplog.records if r.exc_info or r.exc_text]
    assert not [r for r in caplog.records if MARKER in r.getMessage()]


def test_providers_empty_without_auth_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    # The settings validator rejects this env, so patch the cached object the app reads.
    settings = get_settings()
    monkeypatch.setattr(settings, "auth_secret", SecretStr(""))
    assert settings.oauth_github_client_id
    assert settings.oauth_google_client_id
    assert enabled(settings) == []
    with app_client(no_db) as client:
        providers = client.get("/auth/providers")
        start = client.get("/auth/oauth/github/start", follow_redirects=False)
        client.cookies.set(OAUTH_COOKIE, oauth_cookie())
        failed = callback(client, **FULL)
    assert (providers.status_code, providers.json()) == (200, [])
    assert (start.status_code, start.json()["code"]) == (404, "not_found")
    assert OAUTH_COOKIE not in set_cookies(start)
    assert_failed(failed)


@pytest.mark.integration
def test_verified_email_creates_user(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[httpx.Request] = []
    google_http(monkeypatch, email="Alice@Example.COM", seen=seen)
    state = authorize(client, "google")[1]["state"]
    payload = unsign(client.cookies[OAUTH_COOKIE], SECRET)
    assert payload is not None
    response = callback(client, "google", code=CODE, state=state)

    assert (response.status_code, response.headers["location"]) == (302, SUCCESS)
    assert_cleared(response, OAUTH_COOKIE)
    session = set_cookies(response)[SESSION_COOKIE]
    assert session["max-age"] == str(SESSION_TTL_S)
    assert parse_qs(seen[0].content.decode()) == {
        "grant_type": ["authorization_code"],
        "code": [CODE],
        "redirect_uri": [f"{ORIGIN}/api/auth/oauth/google/callback"],
        "client_id": ["google-id"],
        "client_secret": [GOOGLE_SECRET],
        "code_verifier": [payload["verifier"]],
    }
    assert seen[1].headers["authorization"] == f"Bearer {ACCESS_TOKEN}"

    with db_engine.connect() as conn:
        user = conn.execute(text("SELECT id, email, password FROM users")).one()
        identity = conn.execute(
            text("SELECT user_id, provider, provider_user_id FROM oauth_accounts")
        ).one()
        leaks = {s: leaking_tables(conn, s) for s in (CODE, ACCESS_TOKEN, session.value)}
    assert (user.email, user.password) == ("alice@example.com", None)
    assert tuple(identity) == (user.id, "google", "g-1")
    assert session_hashes(db_engine) == {hash_token(session.value)}
    assert leaks == {CODE: [], ACCESS_TOKEN: [], session.value: []}
    me = client.get("/me").json()
    assert (me["tier"], me["email"]) == ("user", "alice@example.com")


@pytest.mark.integration
def test_link_known_identity(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    github_http(monkeypatch, uid=7)
    first = sign_in(client)
    github_http(monkeypatch, uid=7, email=BOB)  # the primary email changed at the provider
    second = sign_in(client)

    with db_engine.connect() as conn:
        emails = conn.execute(text("SELECT email FROM users")).scalars().all()
        identity_users = conn.execute(text("SELECT user_id FROM oauth_accounts")).scalars().all()
    assert emails == [EMAIL]
    assert len(identity_users) == 1
    assert session_hashes(db_engine) == {hash_token(second)}  # the incoming one is rotated
    assert first != second


@pytest.mark.integration
def test_link_verified_email_clears_password_and_sessions(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    register(client)
    client.cookies.clear()
    login = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert login.status_code == 200, login.text
    client.cookies.clear()
    assert count(db_engine, "sessions") == 2

    github_http(monkeypatch, email="ALICE@example.com")
    token = sign_in(client)

    with db_engine.connect() as conn:
        user = conn.execute(text("SELECT id, password FROM users")).one()
        identity_user = conn.execute(text("SELECT user_id FROM oauth_accounts")).scalar_one()
    assert user.password is None
    assert identity_user == user.id
    assert session_hashes(db_engine) == {hash_token(token)}
    client.cookies.clear()
    login = client.post("/auth/login", json={"email": EMAIL, "password": PASSWORD})
    assert login.status_code == 401


@pytest.mark.integration
def test_link_oauth_only_user_keeps_sessions(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    google_http(monkeypatch)
    first = sign_in(client, "google")
    client.cookies.clear()  # another device
    github_http(monkeypatch)
    second = sign_in(client)

    with db_engine.connect() as conn:
        user_id = conn.execute(text("SELECT id FROM users")).scalar_one()
        identities = conn.execute(
            text("SELECT user_id, provider FROM oauth_accounts ORDER BY provider")
        ).all()
    assert [tuple(row) for row in identities] == [(user_id, "github"), (user_id, "google")]
    assert session_hashes(db_engine) == {hash_token(first), hash_token(second)}


@pytest.mark.integration
@pytest.mark.parametrize("provider", ["github", "google"])
def test_no_verified_email_creates_emailless_user(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    password_session = register(client).cookies[SESSION_COOKIE]
    client.cookies.clear()
    fake_http = github_http if provider == "github" else google_http
    fake_http(monkeypatch, email=EMAIL, verified=False)  # an unverified claim on alice's email
    token = sign_in(client, provider)

    with db_engine.connect() as conn:
        rows = conn.execute(text("SELECT email, password IS NOT NULL FROM users")).all()
        identity_email = conn.execute(
            text("SELECT u.email FROM oauth_accounts a JOIN users u ON u.id = a.user_id")
        ).scalar_one()
    assert sorted(rows, key=str) == sorted([(EMAIL, True), (None, False)], key=str)
    assert identity_email is None
    assert session_hashes(db_engine) == {hash_token(password_session), hash_token(token)}
    me = client.get("/me").json()
    assert (me["tier"], me["email"]) == ("user", None)


@pytest.mark.integration
def test_callback_migrates_guest(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    guest_owner = write(client).json()["owner_id"]
    with db_engine.begin() as conn:
        doc = conn.execute(
            text(
                "INSERT INTO documents (owner_id, source, embed_model) "
                "VALUES (:o, 'doc.pdf', 'm') RETURNING id"
            ),
            {"o": guest_owner},
        ).scalar_one()
    github_http(monkeypatch)
    state = authorize(client)[1]["state"]
    response = callback(client, code=CODE, state=state)

    assert response.headers["location"] == SUCCESS
    assert_cleared(response, GUEST_COOKIE)
    with db_engine.connect() as conn:
        user_owner = conn.execute(text("SELECT owner_id FROM users")).scalar_one()
        doc_owner = conn.execute(
            text("SELECT owner_id FROM documents WHERE id = :d"), {"d": doc}
        ).scalar_one()
        owner_ids = conn.execute(text("SELECT id FROM owners")).scalars().all()
    assert doc_owner == user_owner
    assert owner_ids == [user_owner]
    assert count(db_engine, "guests") == 0
    assert client.get("/me").json()["document_count"] == 1


@pytest.mark.integration
def test_callback_conflict_redirects_oauth_failed(
    client: TestClient,
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    github_http(monkeypatch, uid=7)
    sign_in(client)
    client.cookies.clear()

    async def lost_race(db: Any, provider: str, provider_user_id: str) -> None:
        return None  # the other sign-in commits the identity after this lookup

    monkeypatch.setattr(users, "get_user_by_identity", lost_race)
    # A new email, so _link flushes a new owner and user before the identity insert fails.
    github_http(monkeypatch, uid=7, email=BOB)
    tables = ("owners", "users", "oauth_accounts", "sessions", "guests")
    before = [count(db_engine, table) for table in tables]
    state = authorize(client)[1]["state"]
    response = callback(client, code=CODE, state=state)

    assert_failed(response)
    assert [count(db_engine, table) for table in tables] == before
    with db_engine.connect() as conn:
        assert conn.execute(text("SELECT email FROM users")).scalars().all() == [EMAIL]
    assert oauth_warnings(caplog) == ["oauth callback failed: conflict"]


@pytest.mark.integration
@pytest.mark.parametrize("verified", [True, False], ids=["email", "no_email"])
def test_concurrent_callbacks_same_identity_one_user(
    db_override: Callable[[], Any],
    db_engine: Engine,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    verified: bool,
) -> None:
    # Both lookups miss before either inserts; the unique email, or with no verified email
    # the unique identity, makes the second insert wait for the first commit, then fail.
    github_http(monkeypatch, uid=7, verified=verified)
    lookup = after_barrier(users.get_user_by_identity)
    monkeypatch.setattr(users, "get_user_by_identity", lookup)

    def send_with(state: str) -> Callable[[httpx.AsyncClient], Any]:
        async def send(client: httpx.AsyncClient) -> Response:
            client.cookies.set(OAUTH_COOKIE, oauth_cookie(state=state))
            return await client.get(
                "/auth/oauth/github/callback", params={"code": CODE, "state": state}
            )

        return send

    responses = concurrent_requests(db_override, send_with("state-a"), send_with("state-b"))

    assert sorted(r.headers["location"] for r in responses) == sorted([SUCCESS, FAILED])
    winner = next(r for r in responses if r.headers["location"] == SUCCESS)
    loser = next(r for r in responses if r.headers["location"] == FAILED)
    assert_failed(loser)
    tables = ("owners", "users", "oauth_accounts", "sessions")
    assert [count(db_engine, table) for table in tables] == [1, 1, 1, 1]
    assert session_hashes(db_engine) == {hash_token(set_cookies(winner)[SESSION_COOKIE].value)}
    assert oauth_warnings(caplog) == ["oauth callback failed: conflict"]


FAKE = OAuthProvider(
    id="fake",
    name="Fake ID",
    authorize_url="https://id.example.test/authorize",
    token_url="https://id.example.test/token",
    scopes="profile mail",
    identity_urls=("https://id.example.test/me",),
    to_identity=lambda bodies: Identity(bodies[0]["uid"], bodies[0]["mail"], True),
    credentials=lambda settings: ("fake-id", SecretStr("fake-secret")),
)


@pytest.mark.integration
def test_fake_provider_entry_start_and_callback(
    client: TestClient, db_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(PROVIDERS, "fake", FAKE)
    assert {"id": "fake", "name": "Fake ID"} in client.get("/auth/providers").json()
    seen: list[httpx.Request] = []
    me = {"uid": "f-1", "mail": "Carol@Example.com"}
    provider_http(monkeypatch, {FAKE.token_url: TOKEN_REPLY, FAKE.identity_urls[0]: me}, seen)

    url, query = authorize(client, "fake")
    assert url == FAKE.authorize_url
    assert (query["client_id"], query["scope"]) == ("fake-id", "profile mail")
    assert query["redirect_uri"] == f"{ORIGIN}/api/auth/oauth/fake/callback"
    response = callback(client, "fake", code=CODE, state=query["state"])

    assert (response.status_code, response.headers["location"]) == (302, SUCCESS)
    assert parse_qs(seen[0].content.decode())["client_secret"] == ["fake-secret"]
    with db_engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT u.email, a.provider, a.provider_user_id "
                "FROM oauth_accounts a JOIN users u ON u.id = a.user_id"
            )
        ).one()
    assert tuple(row) == ("carol@example.com", "fake", "f-1")


def access_line(path: str) -> str:
    """A uvicorn access record for `path`, after the `uvicorn.access` logger's filters."""
    import app.main  # noqa: F401  configure_logging runs at import and adds the filter

    access = logging.getLogger("uvicorn.access")
    args = ("127.0.0.1:50000", "GET", path, "1.1", 302)
    record = access.makeRecord(
        access.name, logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d', args, None
    )
    assert access.filter(record)
    return record.getMessage()


def test_callback_code_not_in_access_log() -> None:
    for prefix in ("/api", ""):
        path = f"{prefix}/auth/oauth/github/callback"
        line = access_line(f"{path}?code={CODE}&state={STATE}")
        assert line == f'127.0.0.1:50000 - "GET {path} HTTP/1.1" 302'
    assert CODE not in access_line(f"/auth/oauth/google/callback?state=s&code={CODE}")
    # GitHub accepts any redirect_uri under the registered one, so subpaths are callbacks too.
    for path in ("/auth/oauth/github/callback/", "/api/auth/oauth/github/callback/deeper/x"):
        assert access_line(f"{path}?code={CODE}") == f'127.0.0.1:50000 - "GET {path} HTTP/1.1" 302'
    for untouched in (
        "/api/auth/oauth/github/callback",
        "/api/auth/oauth/github/start?next=/chat",
        "/health?probe=1",
        "/api/documents?q=/auth/oauth/x/callback?code=1",
    ):
        assert access_line(untouched) == f'127.0.0.1:50000 - "GET {untouched} HTTP/1.1" 302'


@pytest.mark.integration
def test_callback_logs_reason_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    github_http(monkeypatch)
    state = authorize(client)[1]["state"]
    verifier = str((unsign(client.cookies[OAUTH_COOKIE], SECRET) or {})["verifier"])
    response = callback(client, code=CODE, state=state)
    assert response.headers["location"] == SUCCESS
    session = set_cookies(response)[SESSION_COOKIE].value
    # Provider errors whose bodies echo the request: none of it may reach the logs.
    echo = f"code={CODE} secret={GITHUB_SECRET} token={ACCESS_TOKEN}"
    provider_http(monkeypatch, {GITHUB.token_url: httpx.Response(400, text=echo)})
    assert_failed(callback(client, code=CODE, state=authorize(client)[1]["state"]))
    provider_http(
        monkeypatch,
        {
            GITHUB.token_url: TOKEN_REPLY,
            GITHUB.identity_urls[0]: httpx.Response(401, text=echo),
        },
    )
    assert_failed(callback(client, code=CODE, state=authorize(client)[1]["state"]))

    assert oauth_warnings(caplog) == ["oauth callback failed: provider_failed:HTTPStatusError"] * 2
    # The TestClient logs its own request URLs, which hold the code by design; skip those.
    app_records = [
        r for r in caplog.records if "HTTP Request: GET http://testserver/" not in r.getMessage()
    ]
    logged = "\n".join(f"{r.getMessage()} {r.exc_text or ''}" for r in app_records)
    for secret in (CODE, ACCESS_TOKEN, GITHUB_SECRET, SECRET, state, verifier, session):
        assert secret not in logged
