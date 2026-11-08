# 0007: Retrieval and corrective RAG

- Status: accepted
- Date: 2026-11-08
- Superseded in part by [0008](0008-chat-streaming-and-history.md) (2026-11-08): no checkpointer, history-aware rewriting deferred

## Context
MVP step 10 turns a question into a grounded answer with citations over the owner's `ready` documents (R12). ADR 0006 put vectors in our own `chunks` table, so there is no LlamaIndex retriever to wrap, and retrieval SQL belongs in `app/repositories/vector`. The overview already names the flow `retrieve → grade_chunks → (generate | rewrite_query → retrieve)`. The hard rule still holds: LlamaIndex only in `app/rag`, LangChain/LangGraph only in `app/agents`, plain data between them. Step 11 adds the chat routes and streaming, so step 10 must not need graph changes to stream.

## Decision
- **Add `langgraph` now.** It is part of the declared stack. The corrective loop is a compiled LangGraph graph in `app/agents/workflows`: `retrieve → grade_chunks → (generate | rewrite_query → retrieve)`. `MAX_REWRITES = 2` and `TOP_K = 5` are module constants, not env vars.
- **Contracts (plain data only):**
  - `RetrievedChunk(text, score, metadata)`: frozen dataclass in `app/schemas/chunks.py` next to `EmbeddedChunk`. `metadata = {document_id, source, page}`, with `page` null outside PDFs. It is the only type that crosses into `app/agents`.
  - `app/repositories/vector/chunks.py::search(db, owner_id, embed_model, query_embedding, k) -> list[RetrievedChunk]`. It joins `documents` and filters on `owner_id`, `status = 'ready'`, `documents.embed_model = embed_model` and `vector_dims(embedding) = len(query_embedding)` (a guard against mixed dimensions). It orders by cosine distance; `score = 1 - distance`.
  - `app/rag/retrieval::embed_query(text) -> list[float]`, through `providers.get_embed_model(...).aget_query_embedding`.
  - `app/agents/workflows::answer(question, retrieve) -> {answer, citations}`, non-streaming. `retrieve` is `Callable[[str], Awaitable[list[RetrievedChunk]]]`.
  - `app/services/answers.py::answer_question(db, owner_id, question)` binds `retrieve` as a closure (`embed_query`, then `search` with `settings.embed_model`) and calls the graph. It commits `db` on entry and after each `search`, so no pooled connection idles in a transaction during embedding or LLM calls; callers run it before any write or owner lock. `app/agents` never sees the DB, owners or LlamaIndex.
- **Grader:** one `with_structured_output` call over all chunks, returning the indexes of the relevant ones.
- **Citations:** the chunks the grader kept, deduplicated per `(document_id, page)`. Each has `document_id`, `source`, `page` and `snippet`. The model writes no `[n]` markers.
- **Not found:** empty retrieval goes straight to the fixed "not found in the document" answer, with no citations and zero LLM calls (R12). Empty retrieval does not depend on the query, so a rewrite cannot help. No kept chunk after 2 rewrites gives the same answer. So does a rewrite whose search returns the same chunk texts as the set just graded, without regrading: the grader would judge them the same for the unchanged question (texts are compared, because scores differ per query).
- **Streaming (step 11):** `graph.astream(stream_mode="messages")`, filtered to the `generate` node. No node changes.
- **Security:** chunk text comes from uploads and URLs, so it is untrusted. The grade, rewrite and generate prompts fence chunk text as data, not instructions. Never log the question or chunk text.
- **Scope:** no HTTP endpoint, table, migration or env var in step 10. Step 11 owns routes, SSE, the checkpointer, history-aware rewriting, rate limits and message persistence (superseded in part by ADR 0008: no checkpointer, rewriting deferred).

## Alternatives
- **Plain async loop instead of LangGraph:** fewer deps now, but step 11 would rewrite it for streaming and the checkpointer (superseded in part by ADR 0008: no checkpointer).
- **One grading call per chunk:** up to 5 LLM calls per round instead of 1.
- **Model-written `[n]` markers:** the model can cite wrongly or skip them; the kept chunks are already the evidence.
- **Reranker:** deferred; top 5 by cosine over 20 documents or fewer needs none yet.
- **Hybrid or keyword search:** deferred; needs a full-text index and score fusion with no proven need.
- **HNSW index:** deferred per ADR 0006; the exact scan is fast at MVP size.
- **Provider fallbacks:** deferred; no second provider is configured, so `with_fallbacks` would have nothing to fall back to.
- **Score threshold:** rejected; cosine scores differ per embedding model, and the grader already judges relevance.

## Consequences
- New dependency: `langgraph`.
- The answer path makes at most 1 query embedding and 1 grading call per round, plus 1 rewrite between rounds and 1 generate call: at most 3 rounds.
- `app/rag/reranking` stays an empty placeholder.
- A document embedded with an older `EMBED_MODEL` stays out of search until a re-index.
- Owner isolation for retrieval lives in the repository `WHERE` clause, like every other owner query.
