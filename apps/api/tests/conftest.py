import asyncio
import gzip
import threading
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from http.cookies import Morsel, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from ipaddress import IPv4Address, IPv6Address
from pathlib import Path
from typing import Any

import httpx
import pytest
from alembic.config import Config
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import Connection, Engine, create_engine, inspect, make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.api.deps import DbSession, WriteOwner, client_ip_key
from app.core import storage
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.errors import AppError
from app.services import url_fetch
from app.services.owners import lock_write_owner
from app.services.rate_limit import auth_requests, guest_creations, login_failures, url_fetches

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"
ORIGIN = "http://localhost:5173"  # Settings.public_base_url default

test_router = APIRouter(prefix="/_test")


@test_router.post("/write")
async def _write(owner: WriteOwner, db: DbSession) -> dict[str, str]:
    await lock_write_owner(db, owner)
    await db.commit()
    return {"owner_id": str(owner.owner_id)}


@test_router.post("/write_fail")
async def _write_fail(owner: WriteOwner) -> None:
    raise AppError(409, "x", "y")


@test_router.get("/ip")
async def _ip(request: Request) -> dict[str, str]:
    return {"key": client_ip_key(request)}


EMAIL = "alice@example.com"
PASSWORD = "correct horse battery"


def write(client: TestClient) -> Response:
    response = client.post("/_test/write")
    assert response.status_code == 200, response.text
    return response


def register(client: TestClient, email: str = EMAIL, password: str = PASSWORD) -> Response:
    response = client.post("/auth/register", json={"email": email, "password": password})
    assert response.status_code == 201, response.text
    return response


def count(db_engine: Engine, table: str) -> int:
    with db_engine.connect() as conn:
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()


def set_cookies(response: Response) -> dict[str, Morsel[str]]:
    """The response's Set-Cookie headers, by cookie name."""
    cookies: SimpleCookie = SimpleCookie()
    for header in response.headers.get_list("set-cookie"):
        cookies.load(header)
    return dict(cookies)


def leaking_tables(conn: Connection, secret: str) -> list[str]:
    """Tables with a row holding `secret`, or its bytes as bytea hex, in any column."""
    return [
        table
        for table in inspect(conn).get_table_names()
        if conn.execute(
            text(
                f"SELECT count(*) FROM {table} t WHERE strpos(t::text, :raw) > 0 "
                "OR strpos(t::text, :hex) > 0"
            ),
            {"raw": secret, "hex": secret.encode().hex()},
        ).scalar_one()
    ]


def alembic_config(url: str) -> Config:
    cfg = Config(str(ALEMBIC_INI))
    cfg.attributes["database_url"] = url
    return cfg


@contextmanager
def throwaway_db() -> Iterator[str]:
    """Create `ragidy_test_<hex>` migrated to head, yield its URL, then drop it."""
    server_url = make_url(get_settings().database_url)
    name = f"ragidy_test_{uuid.uuid4().hex}"
    admin = create_engine(server_url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    url = server_url.set(database=name).render_as_string(hide_password=False)
    try:
        command.upgrade(alembic_config(url), "head")
        yield url
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
        admin.dispose()


def pytest_configure(config: pytest.Config) -> None:
    # Runs before test modules import app.main, whose middleware reads settings at import.
    Settings.model_config["env_file"] = None
    get_settings.cache_clear()


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in Settings.model_fields:
        monkeypatch.delenv(name.upper(), raising=False)


@pytest.fixture
def app_env(clean_env: None) -> Iterator[None]:
    """Fresh app settings from defaults plus monkeypatched env (never `.env`) and no rate hits."""
    _reset_app_state()
    yield
    _reset_app_state()


def _reset_app_state() -> None:
    get_settings.cache_clear()
    guest_creations.clear()
    auth_requests.clear()
    login_failures.cache_clear()
    url_fetches.clear()
    storage._client.cache_clear()


Objects = dict[str, tuple[bytes, str]]


@pytest.fixture
def fake_storage(monkeypatch: pytest.MonkeyPatch) -> Objects:
    """In-memory object store, `{key: (data, content_type)}`, in place of `app.core.storage`."""
    objects: Objects = {}

    async def put_object(key: str, data: bytes, content_type: str) -> None:
        objects[key] = (data, content_type)

    async def delete_object(key: str) -> None:
        objects.pop(key, None)

    monkeypatch.setattr(storage, "put_object", put_object)
    monkeypatch.setattr(storage, "delete_object", delete_object)
    return objects


NOTES_MD = b"# Notes\n"


class _Handler(BaseHTTPRequestHandler):
    """Routes for URL fetch tests; sizes and hop counts come from the last path segment."""

    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:
        path, _, query = self.path.partition("?")
        arg = path.rsplit("/", 1)[-1]
        if path.startswith("/redirect/"):
            hops = int(arg)
            if hops:
                self._send(302, b"", Location=f"/redirect/{hops - 1}")
            else:
                self._send(200, b"done")
        elif path == "/to":
            self._send(302, b"", Location=query.removeprefix("url="))
        elif path == "/host":
            self._send(200, self.headers["Host"].encode())
        elif path.startswith("/identity/"):
            # Each hop answers 400 unless the request asked for an uncompressed body.
            hops = int(arg)
            if self.headers["Accept-Encoding"] != "identity":
                self._send(400, b"compression offered")
            elif hops:
                self._send(302, b"", Location=f"/identity/{hops - 1}")
            else:
                self._send(200, b"done")
        elif path == "/gzip":
            self._send(200, gzip.compress(b"a" * 10), **{"Content-Encoding": "gzip"})
        elif path == "/notes.md":
            self._send(200, NOTES_MD)
        elif path.startswith("/bytes/"):
            self._send(200, b"a" * int(arg))
        elif path.startswith("/claims/"):
            # Announces `arg` bytes and sends none: only a Content-Length check can return 413.
            self.send_response(200)
            self.send_header("Content-Length", arg)
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
        elif path.startswith("/chunked/"):
            self.send_response(200)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            for _ in range(int(arg)):
                self.wfile.write(b"1\r\na\r\n")
            self.wfile.write(b"0\r\n\r\n")
        elif path == "/slow":
            time.sleep(2)
            self._send(200, b"late")
        else:
            self._send(404, b"not found")

    def _send(self, status: int, body: bytes, **headers: str) -> None:
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        pass


class _QuietServer(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: Any, client_address: Any) -> None:
        pass  # clients that stop reading early (413, timeouts) reset the connection


@pytest.fixture
def http_server() -> Iterator[str]:
    """A local HTTP server on 127.0.0.1; yields its base URL. Tests never hit the internet."""
    server = _QuietServer(("127.0.0.1", 0), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()
    server.server_close()


@pytest.fixture
def allow_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Let `fetch_url` reach loopback (the local test server); other private IPs stay blocked."""
    allowed = url_fetch._is_allowed

    def is_allowed(ip: IPv4Address | IPv6Address) -> bool:
        return ip.is_loopback or allowed(ip)

    monkeypatch.setattr(url_fetch, "_is_allowed", is_allowed)


class _NoDb:
    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"unexpected DB access: {name}")


async def no_db() -> AsyncIterator[Any]:
    """A `get_db` override for unit tests: any use of the session fails the test."""
    yield _NoDb()


@contextmanager
def app_client(
    get_db_override: Callable[[], AsyncIterator[Any]], **kwargs: Any
) -> Iterator[TestClient]:
    """TestClient on the real app plus the `/_test` routes, with `get_db` overridden.

    Requests carry `Origin: ORIGIN`; pass another per request when PUBLIC_BASE_URL changes.
    """
    from app.main import app

    added = len(app.router.routes)
    app.include_router(test_router)
    app.dependency_overrides[get_db] = get_db_override
    try:
        with TestClient(
            app,
            backend_options={"loop_factory": asyncio.SelectorEventLoop},
            headers={"Origin": ORIGIN},
            **kwargs,
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        del app.router.routes[added:]


def concurrent_requests(
    get_db_override: Callable[[], AsyncIterator[Any]],
    *sends: Callable[[httpx.AsyncClient], Awaitable[Response]],
) -> list[Response]:
    """Run each `send` at once on its own AsyncClient (own cookies, own DB session)."""
    from app.main import app

    async def run() -> list[Response]:
        transport = httpx.ASGITransport(app=app)
        clients = [
            httpx.AsyncClient(
                transport=transport, base_url="http://testserver", headers={"Origin": ORIGIN}
            )
            for _ in sends
        ]
        try:
            return await asyncio.gather(*(send(c) for send, c in zip(sends, clients, strict=True)))
        finally:
            for c in clients:
                await c.aclose()

    app.dependency_overrides[get_db] = get_db_override
    try:
        return asyncio.run(run(), loop_factory=asyncio.SelectorEventLoop)
    finally:
        app.dependency_overrides.clear()


def after_barrier(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    """`fn`, then wait until 2 callers got there: all read before any writes."""
    barrier = asyncio.Barrier(2)

    async def wrapped(*args: Any, **kwargs: Any) -> Any:
        result = await fn(*args, **kwargs)
        await asyncio.wait_for(barrier.wait(), timeout=10)
        return result

    return wrapped


@pytest.fixture(scope="session")
def db_url() -> Iterator[str]:
    with throwaway_db() as url:
        yield url


@pytest.fixture(scope="session")
def db_engine(db_url: str) -> Iterator[Engine]:
    engine = create_engine(db_url)
    yield engine
    engine.dispose()


@pytest.fixture
def db_override(
    db_url: str, db_engine: Engine, app_env: None
) -> Callable[[], AsyncIterator[AsyncSession]]:
    """A `get_db` override on the emptied test database, for tests that need several clients."""
    with db_engine.begin() as conn:
        conn.execute(text("TRUNCATE owners CASCADE"))
    sessions = async_sessionmaker(
        create_async_engine(db_url, poolclass=NullPool), expire_on_commit=False
    )

    async def test_db() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    return test_db


@pytest.fixture
def client(db_override: Callable[[], AsyncIterator[AsyncSession]]) -> Iterator[TestClient]:
    with app_client(db_override) as test_client:
        yield test_client
