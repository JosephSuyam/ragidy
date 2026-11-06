# 0002: Object storage and job queue

- Status: accepted
- Date: 2026-11-04
- Amends: [0001](0001-stack-and-scope.md) (Store: Postgres no longer holds all state)
- Amended: 2026-11-05 (retry wording: no `.with_retry`, see [0004](0004-provider-factory.md))

## Context
Ingestion needs the original file: a failed job retries from it, and a new embedding model needs a re-index from it. ADR 0001 keeps all state in one Postgres database, but it does not say where raw uploads live or how an ingestion job reaches a worker. Ingestion is slow (parse, embed), so it must not run inside the request.

## Decision
- **Object storage: SeaweedFS, through the S3 API.** SeaweedFS (Apache-2.0, official image `chrislusf/seaweedfs`) runs all-in-one in docker compose, with its S3 API on port 8333 published only on localhost; production uses any S3-compatible store. It holds the raw bytes of each upload and of each fetched URL, one object per document. Services validate the input first, then write the object, then insert the `documents` row with its `object_key`.
  - **Key:** the server generates a UUID before the object write and builds the key as `documents/<uuid>`. The key never comes from the filename, the URL or any other user input. The original filename or URL is kept only in `source`.
  - **MIME:** the object's `Content-Type` is the MIME type the server detected and checked against the allowlist, never the client's `Content-Type` header.
  - **Secrets:** storage credentials come only from env or a secret store and are never committed. There are no default credentials. The S3 API (8333) is private, with no anonymous access and no public-read policy. The internal SeaweedFS ports (master 9333, volume 8080, filer 8888, whose HTTP API can read and write every bucket) have no auth and are not published to the host; the URL fetcher's SSRF private-IP block keeps user-supplied URLs from reaching them, and only trusted containers share the compose network. shortcut: hardening them (for example `-filer.disableHttp` or a separate network) is deferred until verified with S3, and comes before any multi-tenant or exposed deployment. Compose fails closed: the `seaweedfs` container refuses to start when `S3_ACCESS_KEY_ID` or `S3_SECRET_ACCESS_KEY` is unset, because SeaweedFS S3 allows anonymous access when no identity is configured.
- **URL fetch: in the request, in `app/services`.** A URL is fetched once, under the existing timeout and size cap, so the worker only ever reads from object storage. Validation and fetch live together in `app/services`, because the fetched bytes go straight to object storage and `app/rag` must never touch it. The fetcher checks the IP it actually connects to, not only the resolved name, to block DNS rebinding. It checks every redirect hop the same way, or refuses redirects.
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
- **MinIO:** rejected. The upstream `github.com/minio/minio` is archived (last push 2026-04-24, last release `RELEASE.2025-10-15T17-29-55Z`), and `minio/minio` on Docker Hub returns 401 to anonymous pulls (checked 2026-11-04).
- **`pgsty/minio` community fork:** a third-party build of an archived project, and a supply-chain risk for a store that holds raw uploads.
- **Garage:** AGPL, and it needs extra config plus layout and key setup before first use.
- **RustFS:** newer and less proven.
- **Local volume:** simplest, but it ties files to one host, the API and worker must share the mount, and it does not move to a managed host.
- **Postgres `bytea`:** one store, but large blobs bloat the database, WAL and backups, and each read loads the whole file into memory.
- **FastAPI `BackgroundTasks`:** no new process, but jobs run in the API process, die on every restart or deploy, have no claim, and compete with requests for CPU.
- **Redis with arq or Celery:** mature queues, but a second stateful service and new dependencies for a single-user app, and job state would be split between Redis and the `documents` row.

## Consequences
- State lives in Postgres (structured data, vectors, the job queue) and object storage (raw files). Backups must cover both.
- One worker process runs beside the API, from the same image with a different command. Compose has the `seaweedfs` service and `make s3` starts it; the api container reaches it at `S3_ENDPOINT_URL=http://seaweedfs:8333`. The `worker` service waits for the worker entry point.
- shortcut: one worker with a startup reset is safe only while a single worker runs. Scaling to more than one worker needs a lease plus guarded writes, and a new ADR.
- Config is S3-style env vars: `S3_ENDPOINT_URL`, `S3_BUCKET`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_REGION`. They are in `.env.example` and `Settings`. Creating the private bucket waits for the storage client.
- The `documents` row stores `attempts` and `run_after timestamptz NOT NULL DEFAULT now()`. The object key is derived from its `id`, not stored (see the amendment).
- Indexing a document first deletes its existing vectors, because a retry after a run that indexed only part of the document would otherwise leave duplicates. The same rule makes a re-index from the original safe.
- A manual retry or re-index resets only a `failed` or `ready` row, with a guarded `UPDATE documents SET status = 'pending', attempts = 0, run_after = now() WHERE id = :id AND status IN ('failed','ready')`. A `pending` or `processing` row is not touched, and the API returns 409 Conflict. The raw file is still in storage. Deleting a document deletes its object. A failed insert after the upload leaves an orphan object, which is harmless.
- Polling adds up to one poll interval of latency. `LISTEN/NOTIFY` is the upgrade if that matters.

## Amendment (2026-11-05)
- There is no `object_key` column. The key is `documents/<id>`, derived from `documents.id`. The service generates that id before the object write, so the key still never comes from user input.
