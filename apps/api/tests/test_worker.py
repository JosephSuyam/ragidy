import asyncio
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from conftest import (
    Objects,
    Sessions,
    add_document,
    add_owner,
    count,
    row,
    run,
    stored_chunks,
)
from sqlalchemy import Engine, text

from app.core import providers
from app.repositories import document_jobs
from app.workers import ingestion

pytestmark = pytest.mark.integration

EMBED_MODEL = "test-embed-model"
TEXT = "First sentence. " * 200  # long enough for several chunks


@pytest.fixture
def worker_db(db_sessions: Sessions, app_env: None, monkeypatch: pytest.MonkeyPatch) -> Sessions:
    """Point the worker at the emptied test database, with EMBED_MODEL as the settings value."""
    monkeypatch.setenv("EMBED_MODEL", EMBED_MODEL)
    monkeypatch.setattr(ingestion, "get_sessionmaker", lambda: db_sessions)
    monkeypatch.setattr(ingestion, "get_engine", lambda: db_sessions.kw["bind"])
    return db_sessions


def queue(db_engine: Engine, objects: Objects, data: bytes, mime: str, **kwargs: Any) -> UUID:
    """A due pending document with its stored object."""
    id = add_document(db_engine, add_owner(db_engine), **kwargs)
    objects[f"documents/{id}"] = (data, mime)
    return id


def embed_with(monkeypatch: pytest.MonkeyPatch, embed: Callable[[], Any]) -> None:
    """Replace the embed model at the provider factory with one whose batch call runs `embed`."""

    class Embedding:
        async def aget_text_embedding_batch(self, texts: list[str]) -> list[list[float]]:
            return await embed()

    monkeypatch.setattr(providers, "get_embed_model", lambda settings: Embedding())


def test_backoff_grows_fourfold_from_30_seconds() -> None:
    assert ingestion.backoff(1) == timedelta(seconds=30)
    assert ingestion.backoff(2) == timedelta(minutes=2)


@pytest.mark.usefixtures("worker_db")
def test_run_once_on_an_empty_queue_returns_false() -> None:
    assert run(ingestion.run_once()) is False


@pytest.mark.usefixtures("worker_db", "mock_embeddings")
def test_success_stores_chunks_and_marks_ready(db_engine: Engine, fake_storage: Objects) -> None:
    id = queue(db_engine, fake_storage, TEXT.encode(), "text/plain", error="earlier failure")

    assert run(ingestion.run_once()) is True

    assert row(db_engine, id)[:4] == ("ready", 1, None, EMBED_MODEL)
    chunks = stored_chunks(db_engine, id)
    assert len(chunks) > 1
    assert [c[0] for c in chunks] == list(range(len(chunks)))
    assert all(c[2] == {"source": "s", "page": None} for c in chunks)


@pytest.mark.parametrize(
    ("data", "mime", "error"),
    [
        (b"x", "image/png", "Unsupported file type."),
        (b"  \n ", "text/plain", "The document has no readable text."),
    ],
)
@pytest.mark.usefixtures("worker_db", "mock_embeddings")
def test_ingestion_error_fails_on_the_first_attempt_with_its_message(
    db_engine: Engine, fake_storage: Objects, data: bytes, mime: str, error: str
) -> None:
    id = queue(db_engine, fake_storage, data, mime)

    assert run(ingestion.run_once()) is True

    assert row(db_engine, id)[:3] == ("failed", 1, error)
    assert count(db_engine, "chunks") == 0


async def embed_crash() -> Any:
    raise RuntimeError("embedding provider down")


@pytest.mark.usefixtures("worker_db")
def test_third_failed_attempt_marks_failed(
    db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    id = queue(db_engine, fake_storage, TEXT.encode(), "text/plain", attempts=2)
    embed_with(monkeypatch, embed_crash)

    assert run(ingestion.run_once()) is True

    assert row(db_engine, id)[:3] == ("failed", 3, "Ingestion failed.")


@pytest.mark.usefixtures("worker_db")
def test_unexpected_error_stores_a_generic_message_and_never_logs_the_source(
    db_engine: Engine,
    fake_storage: Objects,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = "https://example.com/doc.txt?token=url-secret"
    id = queue(db_engine, fake_storage, TEXT.encode(), "text/plain", source=source)

    async def leak() -> Any:
        raise RuntimeError("sk-secret-detail")

    embed_with(monkeypatch, leak)

    with caplog.at_level(logging.INFO, logger=ingestion.__name__):
        assert run(ingestion.run_once()) is True

    requeued = row(db_engine, id)
    assert requeued[:3] == ("pending", 1, "Ingestion failed.")
    assert timedelta(0) < requeued.due_in <= timedelta(seconds=30)
    assert f"Ingestion failed for document {id}, attempt 1" in caplog.text
    assert "url-secret" not in caplog.text


@pytest.mark.usefixtures("worker_db")
def test_job_over_the_timeout_stores_timed_out(
    db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    id = queue(db_engine, fake_storage, TEXT.encode(), "text/plain")
    monkeypatch.setattr(ingestion, "JOB_TIMEOUT_SECONDS", 0.2)

    async def hang() -> Any:
        await asyncio.Event().wait()

    embed_with(monkeypatch, hang)

    assert run(ingestion.run_once()) is True

    assert row(db_engine, id)[:3] == ("pending", 1, "Ingestion timed out.")


@pytest.mark.usefixtures("worker_db", "mock_embeddings")
def test_failure_after_replace_chunks_commits_no_chunks_and_requeues(
    db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    id = queue(db_engine, fake_storage, TEXT.encode(), "text/plain")

    async def crash(*args: Any) -> None:
        raise RuntimeError("database went away")

    monkeypatch.setattr(document_jobs, "mark_ready", crash)

    assert run(ingestion.run_once()) is True

    assert stored_chunks(db_engine, id) == []
    assert row(db_engine, id)[:3] == ("pending", 1, "Ingestion failed.")


def advisory_lock(db_engine: Engine, fn: str) -> bool:
    """Run `fn(WORKER_LOCK_KEY)` on a fresh connection, closed afterwards."""
    with db_engine.connect() as conn:
        return conn.execute(
            text(f"SELECT {fn}(:key)"), {"key": document_jobs.WORKER_LOCK_KEY}
        ).scalar_one()


def test_main_exits_when_another_worker_holds_the_lock(
    worker_db: Sessions, db_engine: Engine
) -> None:
    holder = db_engine.connect()
    try:
        lock_sql = text("SELECT pg_try_advisory_lock(:key)")
        assert holder.execute(lock_sql, {"key": document_jobs.WORKER_LOCK_KEY}).scalar_one()

        with pytest.raises(SystemExit) as exc:
            run(ingestion.main())

        assert exc.value.code == 1
    finally:
        # A pooled connection keeps session-level locks, so unlock before returning it.
        unlock_sql = text("SELECT pg_advisory_unlock(:key)")
        holder.execute(unlock_sql, {"key": document_jobs.WORKER_LOCK_KEY})
        holder.close()


class _Stop(Exception):
    pass


def on_poll(monkeypatch: pytest.MonkeyPatch, handle: Callable[[int], None]) -> None:
    """Replace the worker's POLL_SECONDS sleeps with `handle(n)`, n counting from 1."""
    sleep = asyncio.sleep
    polls = 0

    async def poll(delay: float, *args: Any) -> Any:
        nonlocal polls
        if delay != ingestion.POLL_SECONDS:
            return await sleep(delay, *args)
        polls += 1
        handle(polls)

    monkeypatch.setattr(asyncio, "sleep", poll)


def stop(_: int) -> None:
    raise _Stop


@pytest.mark.usefixtures("worker_db", "mock_embeddings")
def test_main_resets_interrupted_jobs_then_processes_until_idle(
    db_engine: Engine, fake_storage: Objects, monkeypatch: pytest.MonkeyPatch
) -> None:
    id = queue(
        db_engine, fake_storage, TEXT.encode(), "text/plain", status="processing", attempts=1
    )
    on_poll(monkeypatch, stop)

    with pytest.raises(_Stop):
        run(ingestion.main())

    assert row(db_engine, id)[:4] == ("ready", 2, None, EMBED_MODEL)
    assert stored_chunks(db_engine, id) != []
    # main's lock connection closed on exit, so the lock is free again.
    assert advisory_lock(db_engine, "pg_try_advisory_lock")
    assert advisory_lock(db_engine, "pg_advisory_unlock")


def advisory_lock_pids(db_engine: Engine) -> list[int]:
    sql = (
        "SELECT pid FROM pg_locks WHERE locktype = 'advisory' AND granted "
        "AND database = (SELECT oid FROM pg_database WHERE datname = current_database())"
    )
    with db_engine.connect() as conn:
        return list(conn.execute(text(sql)).scalars())


@pytest.mark.usefixtures("worker_db", "mock_embeddings")
def test_main_retakes_the_lock_after_the_lock_connection_drops(
    db_engine: Engine,
    fake_storage: Objects,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    dropped: list[int] = []
    jobs: list[UUID] = []

    def drop_then_stop(poll: int) -> None:
        if poll == 1:  # idle with the lock: kill its connection, then queue a job
            dropped.extend(advisory_lock_pids(db_engine))
            with db_engine.connect() as conn:
                for pid in dropped:
                    conn.execute(text("SELECT pg_terminate_backend(:pid, 5000)"), {"pid": pid})
            jobs.append(queue(db_engine, fake_storage, TEXT.encode(), "text/plain"))
        elif poll == 3:  # poll 2 is main's retry delay; poll 3 is idle after the job
            raise _Stop

    on_poll(monkeypatch, drop_then_stop)

    with caplog.at_level(logging.INFO, logger=ingestion.__name__), pytest.raises(_Stop):
        run(ingestion.main())

    assert len(dropped) == 1
    assert "Ingestion worker lost the database" in caplog.text
    assert caplog.text.count("Ingestion worker lock acquired") == 2
    assert row(db_engine, jobs[0])[:4] == ("ready", 1, None, EMBED_MODEL)
    # The new lock connection closed on exit, so the lock is free again.
    assert advisory_lock_pids(db_engine) == []
