# 0005: Request DB access

- Status: accepted
- Date: 2026-11-05
- Superseded in part by [0008](0008-chat-streaming-and-history.md) (2026-11-08): no checkpointer

## Context
MVP step 6 adds the first routes that touch Postgres: guest creation (R1) behind a `write_owner` dependency, and `GET /me`. Request code is async (the user chose async SQLAlchemy over sync). Alembic and the migration tests already use sync psycopg 3 with `DATABASE_URL=postgresql+psycopg://...`. Later steps need SSE chat and LangGraph's `AsyncPostgresSaver`, which runs on psycopg async (checkpointer superseded in part by ADR 0008). psycopg async refuses Windows' default `ProactorEventLoop` ("Psycopg cannot use the 'ProactorEventLoop' to run in async mode"), and dev runs on Windows.

## Decision
- **Driver: psycopg 3 async**, through `create_async_engine` with the same `postgresql+psycopg://` URL. One driver and one URL serve request code, Alembic, tests and the future checkpointer (superseded in part by ADR 0008: no checkpointer). Declare the extra that SQLAlchemy async needs (greenlet, today only transitive via llama-index-core): `uv add "sqlalchemy[asyncio]>=2.1.8"`. No new package.
- **Event loop.** Use `loop_factory=asyncio.SelectorEventLoop`, never the event-loop policy APIs (deprecated in Python 3.14).
  - Production (Linux, `fastapi run`): uvicorn picks uvloop, which psycopg async supports. No change.
  - Dev server: `make api` runs `fastapi dev`, which reloads in a subprocess, and uvicorn 0.54 then uses `SelectorEventLoop` on Windows. No change. Without reload (`fastapi run` on Windows), uvicorn uses Proactor, so run `uvicorn app.main:app --loop asyncio:SelectorEventLoop` instead.
  - Tests: `TestClient(app, backend_options={"loop_factory": asyncio.SelectorEventLoop})`.
  - Scripts and the worker: `asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)`.
- **Session per request.** `app/core/db.py` holds an `lru_cache`d `async_sessionmaker` over one engine (`pool_pre_ping=True`, `expire_on_commit=False`). The dependency `get_db()` yields one `AsyncSession` and only closes it. Closing rolls back anything not committed. FastAPI caches the dependency per request, so `write_owner` and the route's service share one session. Services commit explicitly, once per use case. `write_owner` creates the guest with `flush()` only and sets the cookie on the response. The write's service commits guest and write together, so a failed write leaves no guest row. The error response is built by the exception handler and carries no cookie.
- **Tests.** Route tests stay sync: `TestClient` inside a `with` block, so no async pytest plugin. The integration fixture creates `ragidy_test_<hex>` and runs Alembic sync, as `tests/test_migrations.py` does. The same URL string then feeds `create_async_engine(url, poolclass=NullPool)`, and `app.dependency_overrides[get_db]` yields sessions from it. `NullPool` keeps connections from outliving the test client's loop. Tests assert DB state with the existing sync engine. If a pure async unit test is ever needed, use the anyio plugin that ships with anyio: `@pytest.mark.anyio` with an `anyio_backend` fixture returning `("asyncio", {"loop_factory": asyncio.SelectorEventLoop})`.
- **Alembic stays sync** (psycopg, `NullPool`), run by the one-shot compose `migrate` service. The future ingestion worker uses the same `app/core/db.py` session maker in its own process.

## Alternatives
- **Sync SQLAlchemy in request code:** rejected by the user. It needs no loop handling, but SSE chat and the async checkpointer (superseded in part by ADR 0008) would then mix sync DB calls into async handlers.
- **asyncpg:** it runs on Proactor, so Windows needs no loop change. But it adds a second driver and a `+asyncpg` URL rewrite next to sync psycopg (Alembic, tests). The checkpointer still needs psycopg async later, so the Windows loop issue returns anyway (checkpointer superseded in part by ADR 0008).

## Consequences
- SSE chat (`POST /chats/{id}/messages`) is natively async.
- Sync or CPU-bound calls, such as LlamaIndex parsing or sync embedding, must run in `asyncio.to_thread` (or `run_in_threadpool`) so they never block the loop.
- Every new async entrypoint on Windows must pass the selector `loop_factory`. Forgetting it fails fast with the psycopg error above, never silently.
- Each async test client gets its own loop, so test engines use `NullPool`. Tests pay one connect per session, which is cheap against a local Postgres.
