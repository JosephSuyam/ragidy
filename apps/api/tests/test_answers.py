from uuid import UUID

import pytest
from conftest import (
    Sessions,
    StubChatModel,
    add_owner,
    add_ready_document,
    axis,
    final_answer,
    in_session,
)
from llama_index.core import MockEmbedding
from sqlalchemy import Engine, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.state import Answer
from app.agents.workflows import NOT_FOUND_ANSWER
from app.core.config import get_settings
from app.services import answers
from app.services.answers import TOP_K, stream_answer_question

pytestmark = [pytest.mark.integration, pytest.mark.usefixtures("mock_embeddings")]

QUESTION = "what is ragidy?"
KEEP_ALL = list(range(TOP_K))


def ask(db_sessions: Sessions, owner_id: UUID) -> Answer:
    return in_session(
        db_sessions, lambda db: final_answer(stream_answer_question(db, owner_id, QUESTION))
    )


def add_doc(
    db_engine: Engine,
    db_sessions: Sessions,
    owner_id: UUID,
    chunk_text: str,
    *,
    status: str = "ready",
    model: str | None = None,
) -> UUID:
    """A one-chunk document embedded by `model`, by default the configured embed model."""
    return add_ready_document(
        db_engine,
        db_sessions,
        owner_id,
        {chunk_text: axis(0)},
        status=status,
        model=model or get_settings().embed_model,
    )


def prompts(model: StubChatModel) -> str:
    return "".join(str(m.content) for call in model.calls for m in call)


def cited(result: Answer) -> list[UUID]:
    return [c["document_id"] for c in result["citations"]]


def test_answer_cites_only_the_owners_documents(
    db_sessions: Sessions, db_engine: Engine, chat_model: StubChatModel
) -> None:
    owner, stranger = add_owner(db_engine), add_owner(db_engine)
    mine = add_doc(db_engine, db_sessions, owner, "Ragidy is a RAG app.")
    add_doc(db_engine, db_sessions, stranger, "A stranger's secret.")
    chat_model.grades = [KEEP_ALL]

    result = ask(db_sessions, owner)

    assert result["answer"] == chat_model.reply
    assert cited(result) == [mine]
    assert "Ragidy is a RAG app." in prompts(chat_model)
    assert "secret" not in prompts(chat_model)


def test_answer_never_cites_a_document_of_another_embed_model(
    db_sessions: Sessions, db_engine: Engine, chat_model: StubChatModel
) -> None:
    owner = add_owner(db_engine)
    current = add_doc(db_engine, db_sessions, owner, "Ragidy is a RAG app.")
    add_doc(db_engine, db_sessions, owner, "Stale text.", model="old-model")
    chat_model.grades = [KEEP_ALL]

    result = ask(db_sessions, owner)

    assert cited(result) == [current]
    assert "Stale text." not in prompts(chat_model)


def test_owner_without_ready_documents_gets_not_found_without_llm_calls(
    db_sessions: Sessions, db_engine: Engine, chat_model: StubChatModel
) -> None:
    owner = add_owner(db_engine)
    add_doc(db_engine, db_sessions, owner, "Still processing.", status="processing")

    result = ask(db_sessions, owner)

    assert result == {"answer": NOT_FOUND_ANSWER, "citations": []}
    assert chat_model.calls == []


def test_no_transaction_is_open_during_embedding_or_chat_calls(
    db_sessions: Sessions,
    db_engine: Engine,
    chat_model: StubChatModel,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = add_owner(db_engine)
    add_ready_document(
        db_engine,
        db_sessions,
        owner,
        {"First hit.": axis(0), "Second hit.": axis(1)},
        model=get_settings().embed_model,
    )
    # One chunk per search, so the rewritten query retrieves a new chunk and gets graded.
    monkeypatch.setattr(answers, "TOP_K", 1)
    chat_model.grades = [[], [0]]
    in_transaction: dict[str, list[bool]] = {"embed": [], "chat": []}

    async def ask_in_open_transaction(db: AsyncSession) -> Answer:
        async def embed(self: MockEmbedding, query: str) -> list[float]:
            in_transaction["embed"].append(db.in_transaction())
            return axis(0) if query == QUESTION else axis(1)

        monkeypatch.setattr(MockEmbedding, "aget_query_embedding", embed)
        chat_model.on_call = lambda: in_transaction["chat"].append(db.in_transaction())
        # Mimics the read transaction the `current_owner` dependency leaves open.
        await db.execute(text("SELECT 1"))
        assert db.in_transaction()
        return await final_answer(stream_answer_question(db, owner, QUESTION))

    result = in_session(db_sessions, ask_in_open_transaction)

    assert [c["snippet"] for c in result["citations"]] == ["Second hit."]
    # Two retrievals; grade, rewrite, grade, generate.
    assert in_transaction == {"embed": [False] * 2, "chat": [False] * 4}
