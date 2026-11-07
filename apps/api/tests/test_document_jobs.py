import asyncio
import uuid
from collections.abc import Awaitable, Callable
from datetime import timedelta
from typing import Any
from uuid import UUID

import pytest
from conftest import Sessions, add_document, add_owner, in_session, row, run, stored_chunks
from sqlalchemy import Engine
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

from app.repositories import document_jobs, documents
from app.repositories.vector.chunks import replace_chunks
from app.schemas.chunks import EmbeddedChunk

pytestmark = pytest.mark.integration

LAST_ATTEMPT_ERROR = "worker stopped during the last attempt"


def unchanged_fields(db_engine: Engine, id: UUID) -> tuple[Any, ...]:
    return tuple(row(db_engine, id))[:5]


@pytest.fixture
def owner(db_sessions: Sessions, db_engine: Engine) -> UUID:
    return add_owner(db_engine)


def test_claim_next_takes_due_pending_rows_oldest_first(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    newer = add_document(db_engine, owner, attempts=1, due_in=-10)
    older = add_document(db_engine, owner, due_in=-60)
    future = add_document(db_engine, owner, due_in=3600)
    for status in ("processing", "ready", "failed"):
        add_document(db_engine, owner, status, due_in=-120)

    claimed = []
    for _ in range(3):
        document = in_session(db_sessions, document_jobs.claim_next)
        claimed.append(document and (document.id, document.status, document.attempts))

    assert claimed == [(older, "processing", 1), (newer, "processing", 2), None]
    assert row(db_engine, older)[:2] == ("processing", 1)
    assert row(db_engine, future)[:2] == ("pending", 0)


def test_claim_next_returns_none_on_an_empty_queue(db_sessions: Sessions) -> None:
    assert in_session(db_sessions, document_jobs.claim_next) is None


def test_concurrent_claims_skip_each_others_locked_rows(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    ids = {add_document(db_engine, owner, due_in=-60), add_document(db_engine, owner, due_in=-30)}

    async def claim_both() -> set[UUID]:
        async with db_sessions() as first, db_sessions() as second:
            a = await document_jobs.claim_next(first)  # its row stays locked until commit
            b = await asyncio.wait_for(document_jobs.claim_next(second), timeout=10)
            await first.commit()
            await second.commit()
            assert a is not None and b is not None
            return {a.id, b.id}

    assert run(claim_both()) == ids
    assert {row(db_engine, id)[:2] for id in ids} == {("processing", 1)}


FINISHERS: dict[str, Callable[[AsyncSession, UUID], Awaitable[None]]] = {
    "mark_ready": lambda db, id: document_jobs.mark_ready(db, id, "new-model"),
    "requeue": lambda db, id: document_jobs.requeue(db, id, "retry later", timedelta(minutes=5)),
    "mark_failed": lambda db, id: document_jobs.mark_failed(db, id, "gave up"),
}


def finish(sessions: Sessions, name: str, id: UUID) -> None:
    in_session(sessions, lambda db: FINISHERS[name](db, id))


def test_mark_ready_sets_the_model_and_clears_the_error(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    id = add_document(db_engine, owner, "processing", attempts=2, error="earlier failure")

    finish(db_sessions, "mark_ready", id)

    assert row(db_engine, id)[:4] == ("ready", 2, None, "new-model")


def test_requeue_sets_pending_with_the_error_after_the_delay(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    id = add_document(db_engine, owner, "processing", attempts=1)

    finish(db_sessions, "requeue", id)

    document = row(db_engine, id)
    assert document[:4] == ("pending", 1, "retry later", "old-model")
    assert timedelta(minutes=4) < document.due_in <= timedelta(minutes=5)


def test_mark_failed_sets_failed_with_the_error(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    id = add_document(db_engine, owner, "processing", attempts=3)

    finish(db_sessions, "mark_failed", id)

    assert row(db_engine, id)[:4] == ("failed", 3, "gave up", "old-model")


@pytest.mark.parametrize("status", ["pending", "ready", "failed"])
@pytest.mark.parametrize("name", list(FINISHERS))
def test_finishing_ignores_rows_not_processing(
    db_sessions: Sessions, db_engine: Engine, owner: UUID, name: str, status: str
) -> None:
    id = add_document(db_engine, owner, status, attempts=1)
    before = unchanged_fields(db_engine, id)

    finish(db_sessions, name, id)

    assert unchanged_fields(db_engine, id) == before


def test_reset_interrupted_retries_or_fails_processing_rows(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    first_try = add_document(db_engine, owner, "processing", attempts=1, error="earlier")
    second_try = add_document(db_engine, owner, "processing", attempts=2)
    last_try = add_document(db_engine, owner, "processing", attempts=3)
    others = {add_document(db_engine, owner, status, attempts=3) for status in ("pending", "ready")}
    others_before = {id: unchanged_fields(db_engine, id) for id in others}

    assert in_session(db_sessions, document_jobs.reset_interrupted) == 3

    assert row(db_engine, first_try)[:3] == ("pending", 1, "earlier")
    assert row(db_engine, second_try)[:3] == ("pending", 2, None)
    assert row(db_engine, last_try)[:3] == ("failed", 3, LAST_ATTEMPT_ERROR)
    assert {id: unchanged_fields(db_engine, id) for id in others} == others_before


def test_worker_lock_refuses_a_second_connection_until_released(db_url: str) -> None:
    async def lock_results() -> list[bool]:
        engine = create_async_engine(db_url, poolclass=NullPool)
        try:
            async with engine.connect() as first:
                results = [await document_jobs.try_worker_lock(first)]
                async with engine.connect() as second:
                    results.append(await document_jobs.try_worker_lock(second))
            async with engine.connect() as after_release:
                results.append(await document_jobs.try_worker_lock(after_release))
            return results
        finally:
            await engine.dispose()

    assert run(lock_results()) == [True, False, True]


def test_replace_chunks_replaces_instead_of_appending(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    id = add_document(db_engine, owner, "processing")
    other = add_document(db_engine, owner, "processing")

    def replace(document_id: UUID, chunks: list[EmbeddedChunk]) -> int:
        return in_session(db_sessions, lambda db: replace_chunks(db, document_id, chunks))

    assert replace(id, [EmbeddedChunk(t, [1.0, 1.0]) for t in "abc"]) == 3
    assert replace(other, [EmbeddedChunk("kept", [9.0, 9.0])]) == 1
    nested = {"source": "café.pdf", "page": None, "tags": {"k": [1, "v"]}}
    second = [
        EmbeddedChunk("x", [0.5, -2.0], {"source": "r.pdf", "page": 1}),
        EmbeddedChunk("y", [3.0, 4.0], nested),
    ]

    assert replace(id, second) == 2

    assert stored_chunks(db_engine, id) == [
        (0, "x", {"source": "r.pdf", "page": 1}, "[0.5,-2]"),
        (1, "y", nested, "[3,4]"),
    ]
    assert stored_chunks(db_engine, other) == [(0, "kept", {}, "[9,9]")]
    assert replace(id, []) == 0
    assert stored_chunks(db_engine, id) == []


def test_get_document_is_owner_filtered(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    stranger = add_owner(db_engine)
    id = add_document(db_engine, owner)

    def get(owner_id: UUID, document_id: UUID) -> UUID | None:
        document = in_session(
            db_sessions, lambda db: documents.get_document(db, owner_id, document_id)
        )
        return document.id if document else None

    assert get(owner, id) == id
    assert get(stranger, id) is None
    assert get(owner, uuid.uuid4()) is None


def test_list_documents_returns_only_the_owners_newest_first(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    stranger = add_owner(db_engine)
    old = add_document(db_engine, owner, created_ago=60)
    new = add_document(db_engine, owner, "ready")
    theirs = add_document(db_engine, stranger)

    def listed(owner_id: UUID) -> list[UUID]:
        rows = in_session(db_sessions, lambda db: documents.list_documents(db, owner_id))
        return [d.id for d in rows]

    assert listed(owner) == [new, old]
    assert listed(stranger) == [theirs]


@pytest.mark.parametrize("status", ["failed", "ready"])
def test_requeue_for_owner_resets_a_finished_document(
    db_sessions: Sessions, db_engine: Engine, owner: UUID, status: str
) -> None:
    id = add_document(db_engine, owner, status, attempts=3, error="boom", due_in=3600)

    document = in_session(db_sessions, lambda db: documents.requeue_for_owner(db, owner, id))

    assert document is not None and (document.id, document.status) == (id, "pending")
    requeued = row(db_engine, id)
    assert requeued[:3] == ("pending", 0, None)
    assert requeued.due_in <= timedelta(0)


@pytest.mark.parametrize("case", ["pending", "processing", "other-owner", "missing"])
def test_requeue_for_owner_refuses_active_foreign_or_missing_documents(
    db_sessions: Sessions, db_engine: Engine, owner: UUID, case: str
) -> None:
    if case == "other-owner":
        id = add_document(db_engine, add_owner(db_engine), "failed", attempts=3)
    else:
        id = add_document(db_engine, owner, case if case != "missing" else "failed", attempts=3)
    target = uuid.uuid4() if case == "missing" else id
    before = unchanged_fields(db_engine, id)

    result = in_session(db_sessions, lambda db: documents.requeue_for_owner(db, owner, target))

    assert result is None
    assert unchanged_fields(db_engine, id) == before
