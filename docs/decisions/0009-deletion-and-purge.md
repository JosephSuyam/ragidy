# 0009: Deletion and guest purge

- Status: accepted
- Date: 2026-11-08
- Related: [0002](0002-object-storage-and-job-queue.md) (objects, job queue, worker), [0003](0003-guest-and-user-accounts.md) (guests, purge, migration), [0005](0005-request-db-access.md) (owner-row lock), [0008](0008-chat-streaming-and-history.md) (chats, messages)

## Context
MVP step 12 adds user deletion (R14) and the guest purge (R10). A document spans an S3 object and DB rows (`documents`, `chunks`), and S3 and Postgres share no transaction, so one side can fail after the other succeeded. The worker may claim a `pending` document at any moment, and a login may migrate a guest while the purge runs. Migration 0001 already has `ix_guests_expires_at` and `ix_sessions_expires_at`. `chunks.document_id` and `messages.chat_id` are `ON DELETE CASCADE`; `documents.owner_id` and `chats.owner_id` are `RESTRICT`.

## Decision
- **Endpoints** (hard delete, `ReadOwner`: never creates a guest, no owner-row lock, no rate limit; `OriginMiddleware` checks the origin because DELETE is not a safe method):
  - `DELETE /documents/{id}` -> `204`, no body. `404 not_found` for an unknown id, another owner's, no cookie, or already deleted. `409 document_busy` while `processing`. `503 storage_unavailable` when the S3 delete fails; the row stays, so the client can retry.
  - `DELETE /chats/{id}` -> `204`; `404 not_found` likewise. Messages cascade.
- **Document delete order: S3 object first, DB row last,** so no orphan object is ever left (Privacy).
  1. Read the document guarded by owner: `404` if missing, `409` if `processing`. Commit, so no transaction is open during the S3 call.
  2. `storage.delete_object(storage.document_key(id))`. A missing key is a no-op in S3; tests verify this on SeaweedFS. `BotoCoreError` or `ClientError` maps to `AppError(503, "storage_unavailable")`. Uploads have no such mapping today (an S3 failure there is an unhandled `500`); this code is new.
  3. Guarded `DELETE FROM documents WHERE id AND owner_id AND status <> 'processing'` (chunks cascade), then commit. No row deleted: `409` if the row is now `processing`, else `404`.
- **Accepted race:** the worker claims a `pending` document between steps 1 and 3. The guarded DELETE then returns `409 document_busy`. The missing object raises boto `ClientError` (`NoSuchKey`), not `IngestionError`, so `_record_failure` requeues it with `backoff` (30 s, then 2 min) until `MAX_ATTEMPTS = 3`, then marks it `failed`. Each claim makes it `processing` again, so a repeated DELETE can get `409` again; between claims it is `pending` and a DELETE succeeds. Accepted as is: the race is rare and resolves itself within about 2.5 min (the backoff window plus polling).
- **Purge** (`app/workers/purge.py`), one transaction per guest, oldest `expires_at` first, at most `PURGE_BATCH = 100` guests per run:
  lock the owner row (`owners.lock_owner`) -> re-check the guest exists and `expires_at <= now()` (else skip: migrated or already purged) -> select its document ids -> delete each object -> delete documents (chunks cascade) -> delete chats (messages cascade) -> `owners.delete_owner` (guest row cascades) -> commit. On any error: roll back that guest only, log its owner id only; the next run finishes it. The batch stops only when the store is down (`BotoCoreError` or an S3 5xx), so one run never waits out the boto retries for every guest. A 4xx on one object (e.g. `AccessDenied`) rolls back that guest only and the batch continues, so one bad object cannot block every later purge. Any other error also continues with the next guest. Either way, one `DELETE FROM sessions WHERE expires_at <= now()` runs last.
- **Lock held across S3 calls.** The "no transaction across slow work" lesson protects the pooled request connections. The purge runs in the worker process on its own session, and the hold is bounded: per guest, at most `MAX_DOCS_GUEST` object deletes, each bounded by the boto timeouts (10 s connect, 60 s read, 3 attempts); per run while S3 is down, one guest's worth, because a store-down error stops the batch. A login migrating that guest at that moment waits; whoever locks the owner row first wins.
- **Schedule:** `_run_locked` in `app/workers/ingestion.py` checks before each `run_once` whether the purge is due: at startup, then every `PURGE_INTERVAL_SECONDS = 900`. A full batch keeps it due. No new process, compose service or env var. No document is mid-ingestion during a purge: the same single worker runs both, and `reset_interrupted` runs at startup. While the worker is down, expired guests stay hidden (R10 AC2) but are not deleted.
- **Citations of a deleted document stay** in `messages.citations` (`document_id`, `source`, `snippet`). History is a record; the user can delete the chat. The step 13 UI must handle a dangling `document_id`.
- **No migration.** The `RESTRICT` owner keys stay as a guard against deleting an owner with rows left.
- **Logging:** delete and purge paths log ids only, never `source`, because a URL can carry tokens.

## Alternatives
- **DB row first, then S3:** a failed S3 delete leaves an orphan object holding user data, which needs a sweeper to find.
- **Soft delete:** keeps user data the user asked to remove, and every query needs a filter.
- **S3 delete queue or outbox:** survives S3 outages without a client retry, but adds a table and a job type; a `503` and a retry are enough for the MVP.
- **Separate purge process or cron:** one more service to deploy and lock; the worker already holds the single-worker lock.
- **Release the owner lock during S3 calls:** a login could migrate the guest mid-purge, so its documents would move to the user after their objects were deleted.
- **Scrub citations on delete:** rewrites history and costs a JSON update per message.

## Consequences
- Deleting is permanent. A `503` keeps the document intact and retryable.
- Purge latency depends on the worker: the worst case is `PURGE_INTERVAL_SECONDS` after expiry while it runs; none while it is down.
- `docs/api/README.md` gets the two DELETE endpoints and `503 storage_unavailable`; `packages/shared-types` gets them in step 13.
- Deferred: orphan-object sweeper, S3 delete queue or outbox, bulk delete, account deletion, rate-limit refunds on delete, env vars for purge timing.
