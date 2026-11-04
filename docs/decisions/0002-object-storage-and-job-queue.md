# 0002: Object storage and job queue

- Status: accepted
- Date: 2026-11-04
- Amends: [0001](0001-stack-and-scope.md) (Store: Postgres no longer holds all state)

## Context
Ingestion needs the original file: a failed job retries from it, and a new embedding model needs a re-index from it. ADR 0001 keeps all state in one Postgres database, but it does not say where raw uploads live or how an ingestion job reaches a worker. Ingestion is slow (parse, embed), so it must not run inside the request.

## Decision
- **Object storage: MinIO, through the S3 API.** MinIO runs in docker compose; production uses any S3-compatible store. It holds the raw bytes of each upload and of each fetched URL, one object per document. Services validate the input first, then write the object, then insert the `documents` row with its `object_key`.
  - **Key:** the server generates a UUID before the object write and builds the key as `documents/<uuid>`. The key never comes from the filename, the URL or any other user input. The original filename or URL is kept only in `source`.
  - **MIME:** the object's `Content-Type` is the MIME type the server detected and checked against the allowlist, never the client's `Content-Type` header.
  - **Secrets:** MinIO credentials come only from env or a secret store and are never committed. Compose must not ship `minioadmin` defaults. The bucket is private, with no public-read policy.
- **URL fetch: in the request, in `app/services`.** A URL is fetched once, under the existing timeout and size cap, so the worker only ever reads from MinIO. Validation and fetch live together in `app/services`, because the fetched bytes go straight to object storage and `app/rag` must never touch it. The fetcher checks the IP it actually connects to, not only the resolved name, to block DNS rebinding. It checks every redirect hop the same way, or refuses redirects.
- **Job queue: the `documents` table.** The row is the job. Services insert it with status `pending`. Exactly one worker process polls and claims one row at a time:
  ```sql
  UPDATE documents SET status = 'processing', attempts = attempts + 1
  WHERE id = (SELECT id FROM documents
              WHERE status = 'pending' AND run_after <= now()
              ORDER BY run_after LIMIT 1 FOR UPDATE SKIP LOCKED)
  RETURNING *;
  ```
  `attempts` counts claims, and `run_after` is only the backoff time ("do not claim before"). Success sets `ready`. After a failure, if `attempts < 3` the row goes back to `pending` with `run_after = now() + backoff`; otherwise it becomes `failed` and stores the error. That is 3 attempts in total, matching `stop_after_attempt=3`. At startup, the worker fails `processing` rows that crashed during their last attempt and resets every other `processing` row to `pending`, so a crashed run is picked up again without a 4th attempt:
  ```sql
  UPDATE documents
  SET status = CASE WHEN attempts >= 3 THEN 'failed' ELSE 'pending' END,
      error  = CASE WHEN attempts >= 3 THEN 'worker stopped during the last attempt' ELSE error END
  WHERE status = 'processing';
  ```
- **Ownership (existing folders):**
  - `app/repositories`: the claim query, the startup reset and every status update, like all DB queries.
  - `app/workers`: the poll loop and the retry and backoff decisions. It runs as its own process.
  - `app/core`: resolves the S3 client from `Settings`, like the providers. Services and workers call it. `app/rag` never touches storage; the worker passes it the bytes and MIME type as plain data.

## Alternatives
- **Local volume:** simplest, but it ties files to one host, the API and worker must share the mount, and it does not move to a managed host.
- **Postgres `bytea`:** one store, but large blobs bloat the database, WAL and backups, and each read loads the whole file into memory.
- **FastAPI `BackgroundTasks`:** no new process, but jobs run in the API process, die on every restart or deploy, have no claim, and compete with requests for CPU.
- **Redis with arq or Celery:** mature queues, but a second stateful service and new dependencies for a single-user app, and job state would be split between Redis and the `documents` row.

## Consequences
- State lives in Postgres (structured data, vectors, the job queue) and object storage (raw files). Backups must cover both.
- One worker process runs beside the API, from the same image with a different command. Compose and the Makefile gain `minio` and `worker` services when the code lands.
- shortcut: one worker with a startup reset is safe only while a single worker runs. Scaling to more than one worker needs a lease plus guarded writes, and a new ADR.
- Config is planned as S3-style env vars: `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_REGION`. They are added to `.env.example` with the code, not before.
- The `documents` row stores the `object_key`, plus `attempts` and `run_after timestamptz NOT NULL DEFAULT now()`.
- Indexing a document first deletes its existing vectors, because a retry after a run that indexed only part of the document would otherwise leave duplicates. The same rule makes a re-index from the original safe.
- A manual retry or re-index resets only a `failed` or `ready` row, with a guarded `UPDATE documents SET status = 'pending', attempts = 0, run_after = now() WHERE id = :id AND status IN ('failed','ready')`. A `pending` or `processing` row is not touched, and the API returns 409 Conflict. The raw file is still in storage. Deleting a document deletes its object. A failed insert after the upload leaves an orphan object, which is harmless.
- Polling adds up to one poll interval of latency. `LISTEN/NOTIFY` is the upgrade if that matters.
