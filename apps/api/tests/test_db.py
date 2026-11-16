import logging
import uuid

import pytest
from conftest import run
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings
from app.core.db import get_engine

pytestmark = pytest.mark.integration

SECRET = "my private question 7f3e"
# The foreign key error quotes chat_id, never content, so only the parameter list could leak it.
INSERT = text(
    "INSERT INTO messages (chat_id, role, content, citations) VALUES (:c, 'user', :q, '[]')"
)


async def insert_error(engine: AsyncEngine) -> str:
    """str() of the error from inserting SECRET as a message of an unknown chat."""
    try:
        async with engine.connect() as conn:
            with pytest.raises(IntegrityError) as caught:
                await conn.execute(INSERT, {"c": uuid.uuid4(), "q": SECRET})
        return str(caught.value)
    finally:
        await engine.dispose()


def test_engine_keeps_bound_values_out_of_errors_and_logs(
    db_url: str,
    app_env: None,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("DATABASE_URL", db_url)
    get_settings.cache_clear()
    get_engine.cache_clear()
    caplog.set_level(logging.DEBUG)
    try:
        hidden = run(insert_error(get_engine()))
    finally:
        get_engine.cache_clear()

    assert "foreign key" in hidden
    assert SECRET not in hidden
    assert SECRET not in caplog.text
    # Control: an engine without hide_parameters leaks it, so the check above can fail.
    assert SECRET in run(insert_error(create_async_engine(db_url)))
