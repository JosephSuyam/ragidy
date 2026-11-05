import asyncio
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config
from fastapi import APIRouter, Request
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from alembic import command
from app.api.deps import DbSession, WriteOwner, client_ip_key
from app.core.config import Settings, get_settings
from app.core.db import get_db
from app.core.errors import AppError
from app.services.rate_limit import guest_creations

ALEMBIC_INI = Path(__file__).resolve().parents[1] / "alembic.ini"

test_router = APIRouter(prefix="/_test")


@test_router.post("/write")
async def _write(owner: WriteOwner, db: DbSession) -> dict[str, str]:
    await db.commit()
    return {"owner_id": str(owner.owner_id)}


@test_router.post("/write_fail")
async def _write_fail(owner: WriteOwner) -> None:
    raise AppError(409, "x", "y")


@test_router.get("/ip")
async def _ip(request: Request) -> dict[str, str]:
    return {"key": client_ip_key(request)}


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
    get_settings.cache_clear()
    guest_creations.clear()
    yield
    get_settings.cache_clear()
    guest_creations.clear()


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
    """TestClient on the real app plus the `/_test` routes, with `get_db` overridden."""
    from app.main import app

    added = len(app.router.routes)
    app.include_router(test_router)
    app.dependency_overrides[get_db] = get_db_override
    try:
        with TestClient(
            app, backend_options={"loop_factory": asyncio.SelectorEventLoop}, **kwargs
        ) as client:
            yield client
    finally:
        app.dependency_overrides.clear()
        del app.router.routes[added:]


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
def client(db_url: str, db_engine: Engine, app_env: None) -> Iterator[TestClient]:
    with db_engine.begin() as conn:
        conn.execute(text("TRUNCATE owners CASCADE"))
    sessions = async_sessionmaker(
        create_async_engine(db_url, poolclass=NullPool), expire_on_commit=False
    )

    async def test_db() -> AsyncIterator[AsyncSession]:
        async with sessions() as session:
            yield session

    with app_client(test_db) as test_client:
        yield test_client
