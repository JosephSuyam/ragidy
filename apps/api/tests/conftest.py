import asyncio
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable, Iterator
from contextlib import contextmanager
from http.cookies import Morsel, SimpleCookie
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
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.errors import AppError
from app.services.owners import lock_write_owner
from app.services.rate_limit import auth_requests, guest_creations, login_failures

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
