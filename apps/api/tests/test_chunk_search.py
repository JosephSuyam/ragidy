import math
from uuid import UUID

import pytest
from conftest import Sessions, add_owner, add_ready_document, axis, in_session
from sqlalchemy import Engine

from app.repositories.vector.chunks import search
from app.schemas.chunks import RetrievedChunk

pytestmark = pytest.mark.integration


def found(
    db_sessions: Sessions, owner_id: UUID, query: list[float], model: str = "m8", k: int = 10
) -> list[RetrievedChunk]:
    return in_session(db_sessions, lambda db: search(db, owner_id, model, query, k))


def texts(chunks: list[RetrievedChunk]) -> list[str]:
    return [c.text for c in chunks]


@pytest.fixture
def owner(db_sessions: Sessions, db_engine: Engine) -> UUID:
    return add_owner(db_engine)


def test_search_returns_only_the_owners_ready_chunks_of_the_model(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    def add(owner_id: UUID, chunk_text: str, **kwargs: str) -> None:
        add_ready_document(db_engine, db_sessions, owner_id, {chunk_text: axis(0)}, **kwargs)

    add(owner, "mine")
    add(add_owner(db_engine), "a stranger's")
    for status in ("pending", "processing", "failed"):
        add(owner, status, status=status)
    add(owner, "stale model", model="old-model")

    assert texts(found(db_sessions, owner, axis(0))) == ["mine"]


def test_search_compares_only_chunks_of_the_query_dimension(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    add_ready_document(db_engine, db_sessions, owner, {"eight": axis(0)})
    add_ready_document(db_engine, db_sessions, owner, {"four": axis(0, 4)}, model="m4")
    # Same model name, other dimension: only the vector_dims guard keeps pgvector from raising.
    add_ready_document(db_engine, db_sessions, owner, {"four as m8": axis(0, 4)})

    assert texts(found(db_sessions, owner, axis(0))) == ["eight"]
    assert texts(found(db_sessions, owner, axis(0, 4), model="m4")) == ["four"]
    assert texts(found(db_sessions, owner, axis(0, 4))) == ["four as m8"]


def test_search_orders_by_cosine_score_and_caps_at_k(
    db_sessions: Sessions, db_engine: Engine, owner: UUID
) -> None:
    near = [1.0, 0.1, 0, 0, 0, 0, 0, 0]
    halfway = [1.0, 1.0, 0, 0, 0, 0, 0, 0]
    id = add_ready_document(
        db_engine,
        db_sessions,
        owner,
        {"orthogonal": axis(1), "halfway": halfway, "near": near},
        source="https://example.com/a",
    )
    add_ready_document(db_engine, db_sessions, owner, {"opposite": [-1.0, 0, 0, 0, 0, 0, 0, 0]})

    every = found(db_sessions, owner, axis(0))
    top = found(db_sessions, owner, axis(0), k=2)

    assert texts(every) == ["near", "halfway", "orthogonal", "opposite"]
    scores = [c.score for c in every]
    expected = [1 / math.hypot(1, 0.1), 1 / math.sqrt(2), 0.0, -1.0]
    assert scores == pytest.approx(expected)
    assert texts(top) == ["near", "halfway"]
    assert top[0].metadata == {"document_id": id, "source": "https://example.com/a", "page": 3}
