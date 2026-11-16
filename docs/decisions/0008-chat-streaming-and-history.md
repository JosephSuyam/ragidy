# 0008: Chat streaming and history

- Status: accepted
- Date: 2026-11-08
- Supersedes in part: [0001](0001-stack-and-scope.md) (Store: LangGraph checkpoints), [0003](0003-guest-and-user-accounts.md) (checkpoints in migration and purge), [0005](0005-request-db-access.md) (the future checkpointer), [0007](0007-retrieval-and-corrective-rag.md) (step 11 scope)

## Context
MVP step 11 exposes the ADR 0007 graph as chat (R12, R13): stream the answer with citations, keep per-chat history, and cap messages per owner per hour. Migrations 0001 and 0002 already create `chats` and `messages` (role, content, citations). Earlier docs promised a LangGraph Postgres checkpointer per chat. FastAPI sends SSE headers before a yield-based generator runs, so an `AppError` raised inside it can no longer become a 401, 404 or 429.

## Decision
- **History is `messages` rows.** No checkpointer, no `langgraph-checkpoint-postgres`, no migration. The graph stays stateless; `app/agents/memory` stays a placeholder.
- **No history-aware query rewriting.** Each question is answered on its own, so follow-ups such as "and the second one?" retrieve poorly. Accepted for the MVP.
- **Endpoints** (errors per `docs/api/README.md`):
  - `POST /chats {title?}` -> `201 {id, title, created_at}`; write owner plus owner-row lock; `401 session_expired`, `429 rate_limited` (guest creation).
  - `GET /chats` -> `200 [{id, title, created_at}]`, newest first; `[]` with no owner, creates no guest.
  - `GET /chats/{id}/messages` -> `200 [{role, content, citations}]`, oldest first; `404 not_found` for another owner or no owner.
  - `POST /chats/{id}/messages {content}` -> `200 text/event-stream` (`fastapi.sse.EventSourceResponse`, 15 s keep-alive ping). Pre-stream errors: `404 not_found`, `429 rate_limited` with `Retry-After`, `401 session_expired`.
- **Input limits** are schema constants: `content` 1 to 4000 characters after stripping, `title` at most 200. No chats-per-owner cap.
- **Pre-stream checks run in a route dependency**, in this order: chat lookup (404), rate-limit hit, owner-row lock, 401 re-check, user-message insert, commit. The route generator only streams.
- **SSE events:** `token` `{"text": str}`, repeated, only from the `generate` node; a not-found answer or a non-streaming model sends one `token` with the full answer. Then `citations` `[{document_id, source, page|null, snippet}]` once (`[]` when not found), then `done` `{}`. On a provider failure mid-stream, `error` `{"code": "answer_failed", "detail": "<fixed user-safe text>"}` replaces `citations` and `done`, and no assistant row is stored.
- **Assistant row:** inserted after the last token, before `citations`. A client disconnect cancels the graph and stores no assistant row; the user message stays unanswered.
- **Owner-isolation exemption:** the assistant insert is keyed by `chat_id` only (`INSERT ... SELECT ... WHERE EXISTS` the chat), because a guest-to-user migration may move the chat mid-stream. It returns false when the chat is gone, logged at info level without the text.
- **Rate limit:** `SlidingWindow(3600)` in `app/services/rate_limit.py`, keyed by `owner_id`, limit `settings.limits(tier).chat_messages_per_hour`. It is hit after the 404 lookup, so foreign ids take no slot, and before the lock. Same single-process shortcut as ADR 0003.
- **Transactions:** streaming commits the read transaction on entry and after each search (ADR 0007). The user message is committed before any LLM call, and the owner lock is released before streaming. No transaction spans an LLM call.
- **Agents:** `stream_answer(question, retrieve)` runs `graph.astream(..., context=AnswerContext(...), stream_mode=["messages", "updates"])`, yields text chunks whose `metadata["langgraph_node"] == "generate"`, then the final `Answer`. No node changes.

## Alternatives
- **LangGraph checkpointer:** a new dependency, tables outside Alembic, and a second copy of history next to `messages`, which the API must return anyway. It only pays off with graph-held memory.
- **History-aware rewriting now:** better follow-ups, but one more LLM call per message and prompt design with no proven need yet.
- **Checks inside the generator:** errors would arrive as `200` streams, so clients could not tell 401, 404 and 429 apart.
- **Store the assistant row on disconnect:** a partial answer would look complete in history.
- **DB-backed rate limit:** works across processes, but needs a table; one API process is enough for the MVP.

## Consequences
- No new dependency or migration. Guest purge and chat delete only remove rows: deleting `chats` cascades to `messages`.
- Deferred: checkpointer, history-aware rewriting, `DELETE /chats` and the purge (step 12), shared types and UI (step 13), DB-backed limits, generated titles, pagination, `Last-Event-ID` resume, provider fallbacks.
- `docs/api/README.md` and `packages/shared-types` get the chat endpoints when they ship.
