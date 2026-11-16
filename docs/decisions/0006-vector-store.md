# 0006: Vector store and ingestion worker

- Status: accepted
- Date: 2026-11-08
- Amends: [0002](0002-object-storage-and-job-queue.md) (worker and retry rules, listed below)

## Context
MVP step 9 adds the ingestion worker, which needs somewhere to write vectors. The docs planned LlamaIndex `PGVectorStore` (`llama-index-vector-stores-postgres`). Its latest release, 0.9.0, still requires `sqlalchemy<2.1`, and the repo is on 2.1.8. It also pulls in `psycopg2-binary` and `asyncpg` (ADR 0005 chose psycopg 3 only), builds its own engines and pool, and creates its own table outside Alembic. Writing the worker also exposed gaps in ADR 0002's job rules.

## Decision
- **Own `chunks` table**, created in Alembic migration `0003_chunks`, which first runs `CREATE EXTENSION IF NOT EXISTS vector`:
  - `id uuid PK DEFAULT gen_random_uuid()`, `document_id uuid NOT NULL` FK `documents ON DELETE CASCADE`, `position int NOT NULL`, `text text NOT NULL`, `metadata jsonb NOT NULL DEFAULT '{}'`, `embedding vector NOT NULL`.
  - `UNIQUE (document_id, position)`. Its index also serves the join to `documents` and the cascade delete.
  - The column type is `pgvector.sqlalchemy.Vector` from the `pgvector` package (0.5.1). No new driver.
- **No dimension on `embedding`.** Changing `EMBED_MODEL` needs no migration. Retrieval (step 10) must filter on `documents.embed_model = <current model>`, because pgvector errors on mixed dimensions and stale vectors must stay out until a re-index.
- **No owner column.** Owner isolation comes from the join to `documents`, so the guest-to-user move still rewrites only `documents.owner_id`.
- **No HNSW index for the MVP.** An exact cosine scan over 20 documents or fewer per owner is fast, and a filtered HNSW scan can return fewer than k rows. shortcut: exact scan, upgrade when per-owner chunk counts make it slow. Upgrade path: one partial expression HNSW index per model dimension, `USING hnsw ((embedding::vector(N)) vector_cosine_ops) WHERE vector_dims(embedding) = N`, limited to 2000 dimensions; queries must then use the same cast and predicate.
- **Layering.** Vector SQL lives in `app/repositories/vector/` (`chunks.py`: `replace_chunks` now, `search` in step 10). `app/rag` parses, chunks and embeds only, and returns plain `app.schemas.chunks.EmbeddedChunk(text, embedding, metadata)`, where `position` is the list index. The worker calls rag, then the repository. LlamaIndex stays in `app/rag`; there is no layering exception. `replace_chunks` deletes the document's rows, then inserts the new ones, so retries and re-indexes never leave duplicates (ADR 0002). `replace_chunks` and `mark_ready` commit in one transaction, so a crash never leaves a `ready` document without chunks.
- **Changes to ADR 0002:**
  1. A manual retry also clears `error`: `SET status = 'pending', attempts = 0, run_after = now(), error = NULL`, with the same `status IN ('failed','ready')` guard.
  2. Success writes the `embed_model` actually used, which can differ from the one stored at upload when `EMBED_MODEL` changed in between.
  3. Each job runs under a 600 s timeout, because Ollama embeddings have no timeout. A timeout counts as a failed attempt.
  4. At startup the worker takes `pg_try_advisory_lock(<constant>)` on a dedicated connection held for the process lifetime, and exits if another worker holds it. This enforces ADR 0002's single-worker shortcut, because a second worker's startup reset would requeue the first worker's in-flight row.
  5. Manual retry is rate-limited per owner by `document_retry_per_hour` (default 10) with the in-memory `SlidingWindow` (`app/services/rate_limit.py`), returning 429 with `Retry-After`, because each retry re-embeds the whole document at provider cost.
  6. `documents.error` is shown to users. It holds only a user-safe message: an `IngestionError`'s own text, else a fixed message, never `str(exc)` of any other exception. The full exception is logged server-side with the document id.
  7. An `IngestionError` (unusable input: an unreadable, password-protected or oversized file, or no readable text) fails the document at once, with no retry. Provider, S3 and timeout errors still get 3 attempts in total, with a backoff of 30 s, then 2 min.
  8. When the database connection drops, the worker reconnects and takes the advisory lock again before it claims another job. It checks the lock connection before each claim, because a dropped connection frees the lock.
  9. Parsing stops at `MAX_TEXT_CHARS = 5_000_000` characters with an `IngestionError`, and strips NUL (`\x00`) from parsed text, because Postgres `text` rejects it.
  10. Embedding sends at most `EMBED_WORKERS = 4` batches at once (`num_workers` in `app/core/providers.py`); LlamaIndex otherwise sends every batch in parallel.

## Alternatives
- **`PGVectorStore`:** rejected for the reasons in Context.
- **Pin `sqlalchemy<2.1`:** downgrades the whole app to suit one plugin, and still brings the second and third drivers.
- **Fixed `vector(N)` column:** HNSW-ready, but every `EMBED_MODEL` change needs a migration.
- **A LlamaIndex vector store adapter in `app/rag` over our table:** a framework wrapper with one caller around two SQL statements, and it puts DB sessions in `app/rag`.
- **`owner_id` on `chunks`:** a cheaper filter, but the guest-to-user move would also rewrite every chunk row.

## Consequences
- The LlamaIndex vector table is gone; `chunks` is in Alembic and the schema diagram. Deleting a document cascades to its chunks.
- `app/rag/indexing` has no job in ingestion; vector writes go through `app/repositories/vector`.
- The migration needs a role allowed to create the extension, or the extension pre-created (`infrastructure/database/init.sql` already does this in compose).
- The timeout cancels the embedding, which is native async. It cannot stop the CPU-bound parse and chunk step, which runs in a thread (`asyncio.to_thread`) and keeps running in the default executor. The abandoned thread can never write, because the worker writes after rag returns. shortcut: upgrade to a killable subprocess if timeouts recur.
- The advisory lock is session-level, so it does not work behind a transaction-mode connection pooler (PgBouncer). The worker must connect to Postgres directly.
- The retry limit is per process and resets on restart, like the other `SlidingWindow` limits.
