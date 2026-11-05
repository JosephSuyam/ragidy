# MVP requirements

Decisions behind this page: [ADR 0001](../decisions/0001-stack-and-scope.md), [ADR 0002](../decisions/0002-object-storage-and-job-queue.md) and [ADR 0003](../decisions/0003-guest-and-user-accounts.md). Each acceptance criterion (AC) is meant to become at least one test.

## Scope
- **In:** guest and user tiers, file upload and URL ingestion, ingestion status and retry, chat with citations over all of the owner's ready documents, per-chat history, deleting your own documents and chats.
- **Out:** workspaces, email verification, password reset, account deletion, admin, choosing documents per chat.

## Tiers
The **owner** of a request is the user its session cookie resolves to, else the guest its guest cookie resolves to. Every document and chat has exactly one owner (ADR 0003).

| | Guest | User |
|---|---|---|
| Identity | `ragidy_guest` cookie, no account | email + password, Google or GitHub; `ragidy_session` cookie |
| Upload and URL size | `UPLOAD_MAX_MB_GUEST` MiB | `UPLOAD_MAX_MB_USER` MiB |
| Types | `UPLOAD_TYPES_GUEST` | `UPLOAD_TYPES_USER` |
| Documents | `MAX_DOCS_GUEST` | `MAX_DOCS_USER` |
| Chat messages | `CHAT_MESSAGES_PER_HOUR_GUEST` per hour | `CHAT_MESSAGES_PER_HOUR_USER` per hour |
| Lifetime | `GUEST_TTL_DAYS` from creation, then purged | until deleted; each session lasts `SESSION_TTL_DAYS` |

All cookies (`ragidy_session`, `ragidy_guest` and `ragidy_oauth`) are `HttpOnly; SameSite=Lax; Path=/`, plus `Secure` when `PUBLIC_BASE_URL` uses `https`. On `http` the flag is omitted, because a cookie sent over http cannot be secure anyway and Safari may refuse `Secure` cookies on `http://localhost`. Production must use `https`. `ragidy_session` has `Max-Age` of `SESSION_TTL_DAYS` days. The database stores only the SHA-256 hash of a guest or session token. Tokens are 32 random bytes from `secrets`.

## Feature requirements

### R1 Guest session
- [ ] Given no cookie, when a client makes its first write (upload, URL, new chat), then the server creates a guest, sets `ragidy_guest` with `Max-Age` of `GUEST_TTL_DAYS` days, and the write belongs to that guest.
- [ ] Given no cookie, when a client lists documents or chats, then it gets `200` with an empty list and no guest row is created.
- [ ] Given guests A and B, when B reads, retries or deletes A's document or chat by id, then the response is `404`.
- [ ] No table contains the raw cookie value; `guests` holds only its hash.
- [ ] An unknown or expired guest cookie is treated as no cookie.
- [ ] A client IP key (see Security) may create `GUEST_CREATE_PER_IP_PER_HOUR` guests an hour. Over that, the write returns `429 rate_limited` with `Retry-After` and creates no guest.

### R2 Register with email and password
- [ ] Given a new email and a password of 8 to 128 characters, when `POST /auth/register` is called, then it returns `201`, creates the user and a session, and sets `ragidy_session`.
- [ ] The email is trimmed and lowercased. An email that already exists, including on an OAuth-only account, returns `409 email_taken`. `users.email` has a unique index on the normalized email (it is stored normalized, enforced by a CHECK, under a plain unique constraint), so a concurrent duplicate registration also returns `409 email_taken`.
- [ ] A password outside 8 to 128 characters returns `422`.
- [ ] The stored hash starts with `$argon2id$`.
- [ ] The session is issued as in R3.
- [ ] Guest data migrates (R6).

### R3 Log in with email and password
- [ ] Given valid credentials, when `POST /auth/login` is called, then it returns `200`, deletes the incoming session row if there is one, and sets `ragidy_session` to a newly generated token. A planted session cookie therefore never becomes logged in (no session fixation). Register (R2) and the OAuth callback (R4) issue sessions the same way.
- [ ] A wrong password, an unknown email, and an account without a password all return the same `401 invalid_credentials`.
- [ ] When the stored hash uses outdated parameters, a successful login rehashes it.
- [ ] Guest data migrates (R6).

Account enumeration is accepted: `409 email_taken` (R2) already reveals whether an email exists. The rate limits in Security bound it.

### R4 Log in with Google or GitHub (OAuth / OpenID Connect)
- [ ] `GET /auth/providers` lists exactly the providers whose client id is set.
- [ ] `GET /auth/oauth/{provider}/start` returns `302` to the provider with `state`, a PKCE `S256` challenge and `redirect_uri = <PUBLIC_BASE_URL>/api/auth/oauth/{provider}/callback`. It sets `ragidy_oauth` with the cookie attributes in Tiers (`Secure` only on `https`), signed with `AUTH_SECRET`, which expires after 10 minutes and holds the state, the PKCE verifier and the provider. An unknown or disabled provider returns `404`.
- [ ] Given a missing, expired or tampered `ragidy_oauth` cookie, a state mismatch, or a provider error, when the callback runs, then it redirects to `<PUBLIC_BASE_URL>/login?error=oauth_failed` and creates no session.
- [ ] The identity (provider user id, email, email verified) comes from the provider over TLS with the access token: Google's userinfo `email_verified`, GitHub's `/user/emails` entry that is `primary` and `verified`.
- [ ] The provider email is trimmed and lowercased before matching or storing.
- [ ] Account linking follows ADR 0003: a known `(provider, provider user id)` logs in; else a verified email that matches a user links to that user; else a verified email creates a user with that email; else a user with no email is created.
- [ ] Linking by verified email to a user that has a password removes the password and deletes that user's other sessions.
- [ ] After linking, `GET /documents` and `GET /chats` list every document and chat of the account, including any added before linking. Accepted risk: a squatter's documents and chats stay in the account; these existing lists let the user find and delete them (R14).
- [ ] Success redirects to `<PUBLIC_BASE_URL>/` with `ragidy_session` set, and guest data migrates (R6).
- [ ] Adding a provider needs only its config and one provider entry in `app/core`: a test registers a fake entry and runs start and callback against it.

### R5 Log out
- [ ] Given a session, when `POST /auth/logout` is called, then it returns `204`, deletes the session row and clears the cookie (`Max-Age=0`).
- [ ] The old token no longer resolves to the user. Logout without a session also returns `204`.

### R6 Guest to user migration
- [ ] Given a guest with documents and chats, when register or any login succeeds, then in the same transaction, after `SELECT ... FOR UPDATE` on the guest's `owners` row, every guest document and chat moves to the user, the guest row is deleted, and `ragidy_guest` is cleared.
- [ ] Moved documents keep their id, status, object and vectors; moved chats keep their full history; a `pending` document still reaches `ready`.
- [ ] Migration ignores `MAX_DOCS_USER`. A user over the cap keeps every document, and further uploads return `409 document_limit_reached` until they delete enough.
- [ ] If the guest's `owners` row is already gone at `FOR UPDATE` (the purge won the race), there is nothing to migrate and the login succeeds. Only a failure while moving existing rows fails the login, and then nothing moves.
- [ ] An upload, URL, chat-creation or message request that reaches its insert after the guest's `owners` row was deleted by the migration returns `401 session_expired` and leaves no row or object (R9, R12).

### R7 Upload size and types per tier
- [ ] A file larger than `UPLOAD_MAX_MB_<tier> × 1024 × 1024` bytes returns `413 too_large`. The server stops reading at limit + 1 byte and writes no object and no row. A file of exactly the limit is accepted.
- [ ] The type is decided from the bytes, never the client `Content-Type` header. A detected type whose name is not in `UPLOAD_TYPES_<tier>` returns `415 unsupported_type`.
- [ ] Type names map to MIME types in `app/core`:

  | Name | Server-detected MIME |
  |---|---|
  | `pdf` | `application/pdf` |
  | `docx` | `application/vnd.openxmlformats-officedocument.wordprocessingml.document` |
  | `txt` | `text/plain` |
  | `md` | `text/markdown`, or `text/plain` when the filename or URL path ends in `.md` |
  | `html` | `text/html` |
- [ ] At startup, an unknown name (for example `UPLOAD_TYPES_GUEST=pdf,exe`) or an empty list fails with an error that names the setting and the value. Names are trimmed and lowercased.
- [ ] `GET /me` returns the owner's tier limits: `max_upload_mb`, `upload_types`, `max_docs` and `chat_messages_per_hour`. The UI uses them to reject a file by size or type before it uploads; the server still enforces every limit.

### R8 URL ingestion limits
- [ ] Fetched URL content over `UPLOAD_MAX_MB_<tier>` MiB returns `413 too_large`, stops reading at limit + 1 byte, and writes nothing.
- [ ] The fetched bytes pass the same type check as R7.
- [ ] A non-http(s) URL, or a private, loopback or link-local IP on the connected address or any redirect hop, returns `422 url_blocked` (ADR 0002).
- [ ] A timeout or a non-2xx response returns `422 url_fetch_failed`.

### R9 Document caps
- [ ] Given an owner with `MAX_DOCS_<tier>` documents in any status, when they upload or add a URL, then the response is `409 document_limit_reached`, the message states the cap, there is no row, and the object is removed.
- [ ] The cap is checked before the body is read, and again at insert. The service writes the object first. Then, in one transaction, it takes `SELECT ... FOR UPDATE` on the owner's `owners` row, counts documents and inserts the row, so concurrent uploads never exceed the cap.
- [ ] If the cap check or the insert fails, the service deletes the object it wrote. If the owner row is gone (the guest was purged or migrated mid-request), the upload fails the same way with `401 session_expired`; the client refreshes its session state (`GET /me`) and retries. A crash between the write and the delete leaves an orphan object, which ADR 0002 accepts as harmless.
- [ ] Deleting a document frees a slot.

### R10 Guest expiry
- [ ] A guest's `expires_at` is its creation time plus `GUEST_TTL_DAYS`. Activity does not extend it. A changed `GUEST_TTL_DAYS` applies to new guests only.
- [ ] After `expires_at`, the cookie no longer resolves, so the data is hidden before the purge runs.
- [ ] The worker purges expired guests at least once an hour. Each guest's purge starts with `SELECT ... FOR UPDATE` on its `owners` row and re-checks `expires_at` under that lock, so it never deletes data that just moved (R6). An upload, URL, chat-creation or message request that reaches its insert after the purge deleted the owner row returns `401 session_expired` (R9, R12). After a purge, no document row, object, vector, chat row or checkpoint of that guest remains.
- [ ] The same purge deletes expired sessions.

### R11 Ingestion status and retry
- [ ] Upload and URL return `202` with the document and status `pending`. `GET /documents/{id}` shows `status`, `error` and `attempts`.
- [ ] Status moves `pending → processing → ready | failed`, with 3 attempts in total (ADR 0002). A `failed` document has a non-empty `error`.
- [ ] `POST /documents/{id}/retry` on a `failed` or `ready` document returns `202` with status `pending` and `attempts` 0. On `pending` or `processing` it returns `409 document_busy`.
- [ ] The UI shows each document's status and a retry action on `failed`.

### R12 Chat with citations
- [ ] `POST /chats` inserts the chat in one transaction after `SELECT ... FOR UPDATE` on the owner's `owners` row, like the R9 insert. If the row is gone (the guest was purged or migrated mid-request), it returns `401 session_expired` and creates no chat. Rule: every write that depends on a guest-owned row (document, URL, chat or message insert) takes this owner-row lock first, and returns `401 session_expired` when the owner row or the row it depends on is gone.
- [ ] `POST /chats/{id}/messages` streams the answer as server-sent events: `token` events, then one `citations` event, then `done`.
- [ ] `POST /chats/{id}/messages` takes `SELECT ... FOR UPDATE` on the chat owner's `owners` row before it inserts the user message, and before the stream opens. If the owner row or the chat is gone (a purge or migration ran mid-request), it returns `401 session_expired` and creates no message.
- [ ] The assistant message is inserted after the SSE stream ends, when the response is already `200`. After a migration it succeeds, because the chat id does not change and the chat is now under the user's owner. If a purge deleted the chat meanwhile, the insert finds the chat gone, is dropped and logged at info level, and no error reaches the client, because the stream already finished.
- [ ] Retrieval searches all of the owner's `ready` documents, and only those. Each citation has `document_id`, `source`, `page` (or null) and `snippet`, and every cited document belongs to the owner.
- [ ] With no ready documents, or no relevant chunk after 2 rewrites, the answer says it was not found in the document and cites nothing.
- [ ] Another owner's chat id returns `404`.
- [ ] An owner may send `CHAT_MESSAGES_PER_HOUR_<tier>` messages an hour. Over that, `POST /chats/{id}/messages` returns `429 rate_limited` with `Retry-After` before any LLM call.

### R13 History
- [ ] `GET /chats` lists the owner's chats, newest first.
- [ ] `GET /chats/{id}/messages` returns the messages in order, with the citations of each assistant message.
- [ ] History survives an API restart and the guest-to-user migration.

### R14 Deletion
- [ ] `DELETE /documents/{id}` returns `204` and deletes the row, the object and the vectors. Later answers never cite it.
- [ ] Deleting a `processing` document returns `409 document_busy`. The delete is one guarded statement, so it cannot race the worker's claim.
- [ ] `DELETE /chats/{id}` returns `204` and deletes the chat row and its checkpoint thread.
- [ ] Deleting another owner's document or chat returns `404`.

## API contract
Paths are API-side and unprefixed, like `/health`. The browser reaches them under `/api` on the one origin `PUBLIC_BASE_URL` (for example `POST <PUBLIC_BASE_URL>/api/auth/login`), because the web server proxies `/api/*` to the API and strips the prefix. Errors use `{"code": "<code>", "detail": "<message>"}`. Every route below can also return `403 origin_mismatch` (state-changing methods only), `404 not_found` (unknown id or another owner's id) and `422` (validation).

| Method | Path | Request | Response | Errors |
|---|---|---|---|---|
| GET | `/me` | none | `200 {tier, email, limits: {max_upload_mb, upload_types, max_docs, chat_messages_per_hour}, document_count, guest_expires_at}` | none |
| POST | `/auth/register` | `{email, password}` | `201 {id, email}`, sets `ragidy_session` | `409 email_taken`, `429 rate_limited` |
| POST | `/auth/login` | `{email, password}` | `200 {id, email}`, sets `ragidy_session` | `401 invalid_credentials`, `429 rate_limited` |
| POST | `/auth/logout` | none | `204`, clears `ragidy_session` | none |
| GET | `/auth/providers` | none | `200 [{id, name}]` | none |
| GET | `/auth/oauth/{provider}/start` | none | `302` to the provider, sets `ragidy_oauth` | `404` |
| GET | `/auth/oauth/{provider}/callback` | `code`, `state` | `302 <PUBLIC_BASE_URL>/`, sets `ragidy_session` | `302 <PUBLIC_BASE_URL>/login?error=oauth_failed` |
| POST | `/documents` | multipart `file` | `202 {document}` | `401 session_expired` (owner gone mid-request), `409 document_limit_reached`, `413 too_large`, `415 unsupported_type`, `429 rate_limited` (guest creation) |
| POST | `/documents/url` | `{url}` | `202 {document}` | as above, plus `422 url_blocked`, `422 url_fetch_failed` |
| GET | `/documents` | none | `200 [{document}]` | none |
| GET | `/documents/{id}` | none | `200 {document}` | none |
| POST | `/documents/{id}/retry` | none | `202 {document}` | `409 document_busy` |
| DELETE | `/documents/{id}` | none | `204` | `409 document_busy` |
| POST | `/chats` | `{title?}` | `201 {chat}` | `401 session_expired` (owner gone mid-request), `429 rate_limited` (guest creation) |
| GET | `/chats` | none | `200 [{chat}]` | none |
| GET | `/chats/{id}/messages` | none | `200 [{role, content, citations}]` | none |
| POST | `/chats/{id}/messages` | `{content}` | `200 text/event-stream` | `401 session_expired` (owner or chat gone mid-request), `429 rate_limited` |
| DELETE | `/chats/{id}` | none | `204` | none |

`{document}` is `{id, source, status, error, attempts, created_at}`. `{chat}` is `{id, title, created_at}`. `tier` is `guest` or `user`; with no cookie it is `guest` and `guest_expires_at` is null. `limits` are the tier's settings (R7, R9, R12): size in MiB, type names, document cap and chat messages per hour.

## Non-functional requirements

### Security
- [ ] Passwords are hashed with argon2id (`argon2-cffi` defaults); plain passwords are never logged or stored. Hash and verify run in a threadpool behind a fixed concurrency cap (an internal constant, not config), because each call is CPU-bound and takes about 64 MiB.
- [ ] Rate limits: `POST /auth/register` and `POST /auth/login` allow `RATE_LIMIT_AUTH_PER_MINUTE` requests a minute per client IP key. Login allows `LOGIN_MAX_FAILURES` failures per `LOGIN_FAILURE_WINDOW_MINUTES` minutes per (email, client IP key), so an attacker on another IP cannot lock out a victim. Guest creation (R1) and chat messages (R12) have their own limits. Excess returns `429 rate_limited` with `Retry-After`.
  shortcut: the counters live in memory per API process, so they reset on restart and only work with one API process; move them to Postgres before running more than one API process.
  Each check prunes expired windows, so keys built from random emails or rotated IPs do not grow memory without limit.
  The chat counter is keyed by owner, so it starts fresh after the guest-to-user migration (R6). This is accepted.
- [ ] Client IP: the socket peer address by default. Forwarded headers count only when the peer is in `TRUSTED_PROXIES`; empty (the default) trusts no proxy. `app/main.py` adds uvicorn's `ProxyHeadersMiddleware` with `trusted_hosts` set to the normalized `TRUSTED_PROXIES` strings (for example `10.0.0.0/8`, `192.168.1.1/32`), because the middleware takes strings (no new dependency). The API runs with `--no-proxy-headers`, because uvicorn's own handling trusts `127.0.0.1` by default, so `TRUSTED_PROXIES` is the only source of trust. A test shows that a spoofed `X-Forwarded-For` from an untrusted peer does not change the key. Behind the web container, set `TRUSTED_PROXIES` to its address, or all clients share one key.
- [ ] Rate-limit IP key: every per-IP limit (guest creation, auth requests, login failures) keys an IPv4 client by its full address and an IPv6 client by its `/64` prefix, because one IPv6 client controls a whole `/64` and could rotate through it. An IPv4-mapped IPv6 peer (`::ffff:a.b.c.d`) is first unwrapped with `ipaddress.IPv6Address.ipv4_mapped` and keyed by that full IPv4 address. The key function never raises: ASGI allows `scope["client"]` to be `None`, so a missing peer is keyed by one shared key, `"unknown"`, and a peer host that is not a valid IP (Starlette's TestClient sends `"testclient"`) is keyed by its raw host string. The test `test_non_ip_peer_keyed_without_error` shows that both cases return a key and raise no error. The test `test_ipv6_same_64_shares_counter` shows that two requests from different addresses in the same IPv6 `/64` share one counter. The test `test_ipv4_mapped_keyed_as_ipv4` shows that a mapped peer shares a counter with the same IPv4 address, and not with other IPv4 clients.
- [ ] CSRF: cookies are `SameSite=Lax`, and middleware in `app/api/middleware` rejects every POST, PUT, PATCH and DELETE whose `Origin` header is missing or differs from the origin of `PUBLIC_BASE_URL`, with `403 origin_mismatch`. The comparison is an exact string match against the normalized `PUBLIC_BASE_URL` (Configurability).
- [ ] Owner isolation: every repository function for documents and chats that routes or services call takes `owner_id` and puts it in the `WHERE` clause. The worker queries (claim, startup reset, status updates of status, attempts and error, object-key reads by document id, purge) are the only exemptions, named as such and called only from `app/workers`. Retrieval gets only the owner's document ids as plain data. A two-owner test covers read, retry, delete and chat citations.
- [ ] SSRF: URL fetching follows ADR 0002 (http(s) only, no private, loopback or link-local IPs on the connected address or any redirect hop, timeout, size cap).
- [ ] At startup, a provider with a client id but no client secret, any enabled provider with an empty `AUTH_SECRET`, or a set `AUTH_SECRET` shorter than 32 characters fails with an error that names the setting.
- [ ] Before the public guest tier is deployed, the internal SeaweedFS ports are hardened as ADR 0002 requires (its deferred `-filer.disableHttp` or separate-network step).

### Configurability
Every limit is read from env through `Settings` (`app/core`). Integers must be 1 or more, and each `TRUSTED_PROXIES` entry must be an IP or CIDR, or startup fails. Each entry is normalized to a network string (`10.0.0.0/8` stays as is, `192.168.1.1` becomes `192.168.1.1/32`), the form `ProxyHeadersMiddleware` takes.

| Env var | Default | Meaning |
|---|---|---|
| `UPLOAD_MAX_MB_GUEST` | `3` | Guest upload and URL size limit in MiB (3 = 3 × 1024 × 1024 bytes) |
| `UPLOAD_MAX_MB_USER` | `5` | User upload and URL size limit in MiB |
| `UPLOAD_TYPES_GUEST` | `pdf,docx,txt,md,html` | Guest type names, a subset of the supported names |
| `UPLOAD_TYPES_USER` | `pdf,docx,txt,md,html` | User type names, a subset of the supported names |
| `MAX_DOCS_GUEST` | `3` | Guest document cap |
| `MAX_DOCS_USER` | `20` | User document cap |
| `GUEST_TTL_DAYS` | `7` | Days from guest creation until its data is hidden and purged |
| `SESSION_TTL_DAYS` | `30` | Days a login session lasts |
| `AUTH_SECRET` | empty | Signs the short-lived OAuth state and PKCE cookie; at least 32 characters when set; required when any OAuth provider is enabled |
| `PUBLIC_BASE_URL` | `http://localhost:5173` | The web origin the browser uses; builds the OAuth redirect URI `<PUBLIC_BASE_URL>/api/auth/oauth/{provider}/callback` and post-login redirects; its origin is the only allowed `Origin`. Normalized to a lowercase scheme and host with the default port dropped, so the `Origin` check compares exact strings. `https` adds `Secure` to every cookie |
| `OAUTH_GOOGLE_CLIENT_ID` | empty | Enables Google when set |
| `OAUTH_GOOGLE_CLIENT_SECRET` | empty | Google client secret |
| `OAUTH_GITHUB_CLIENT_ID` | empty | Enables GitHub when set |
| `OAUTH_GITHUB_CLIENT_SECRET` | empty | GitHub client secret |
| `RATE_LIMIT_AUTH_PER_MINUTE` | `10` | Register and login requests per client IP key (IPv4 address or IPv6 `/64`) per minute |
| `LOGIN_MAX_FAILURES` | `5` | Failed logins per (email, client IP key) per window |
| `LOGIN_FAILURE_WINDOW_MINUTES` | `15` | Window for `LOGIN_MAX_FAILURES`, in minutes |
| `TRUSTED_PROXIES` | empty | Comma-separated IPs or CIDRs whose forwarded headers count, normalized to network strings; empty ignores forwarded headers |
| `GUEST_CREATE_PER_IP_PER_HOUR` | `10` | Guests one client IP key (IPv4 address or IPv6 `/64`) may create per hour |
| `CHAT_MESSAGES_PER_HOUR_GUEST` | `20` | Chat messages per guest per hour |
| `CHAT_MESSAGES_PER_HOUR_USER` | `100` | Chat messages per user per hour |

### Privacy
- [ ] A guest's documents, objects, vectors, chats and checkpoints are purged after `GUEST_TTL_DAYS` (R10), and hidden from the moment the guest expires.
- [ ] Deleting a document or chat removes its object, vectors and checkpoint thread, not only the row (R14).
- [ ] Logs never contain passwords, tokens, cookie values or OAuth codes.

## Folder ownership
- Routes: `app/api/routes`. Origin check: `app/api/middleware`. `ProxyHeadersMiddleware` setup: `app/main.py`. In-memory rate-limit counters: `app/services`.
- Auth, session, guest and migration logic: `app/services`. Queries: `app/repositories`. Tables: `app/models`.
- OAuth provider entries, the type-to-MIME map and `Settings`: `app/core`.
- Guest and session purge: `app/workers`, calling `app/rag/indexing` (vectors), `app/agents/memory` (checkpoints), `app/core` (objects) and `app/repositories` (rows).
- Web sign-in, register and logout: `apps/web/src/features/authentication`.
- `--no-proxy-headers` on the API run command (devops, build step): `infrastructure/docker` and `Makefile`.
- `/api` proxy (later step): `apps/web` Vite config in dev, and the web server in `infrastructure/docker` in production (:8080).
