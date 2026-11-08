# API

Base URL in development: `http://localhost:8000`. The browser reaches the same paths under `/api` on the web origin (`http://localhost:5173/api` with `make web`, `http://localhost:8080/api` with `make up`), because the web server proxies `/api/*` to the API and strips the prefix. FastAPI serves interactive docs at `/docs` and the OpenAPI schema at `/openapi.json`.

| Method | Path | Response | Notes |
|---|---|---|---|
| GET | `/health` | `{"status": "ok"}` | Liveness check |
| GET | `/me` | `200 {tier, email, limits: {max_upload_mb, upload_types, max_docs, chat_messages_per_hour}, document_count, guest_expires_at}` | The owner's tier and limits. `ragidy_session` wins over `ragidy_guest`. A user gets `tier` `user`, its `email`, and `guest_expires_at` `null`. With no cookie, or an unknown or expired one: `tier` is `guest`, `email` and `guest_expires_at` are `null`, `document_count` is `0`, and no row is written |
| POST | `/auth/register` | `201 {id, email}` | Body `{email, password}`: a valid email and a password of 8 to 128 characters. Sets `ragidy_session`. Errors: `409 email_taken`, `422`, `429 rate_limited` |
| POST | `/auth/login` | `200 {id, email}` | Body `{email, password}`: email at most 254 characters, password at most 128, else `422`. Replaces the incoming session with a new one. Errors: `401 invalid_credentials`, `429 rate_limited` |
| POST | `/auth/logout` | `204` | Deletes the session row and clears `ragidy_session` (`Max-Age=0`). Also `204` without a session |
| GET | `/auth/providers` | `200 [{id, name}]` | Enabled OAuth providers: those with a client id set, and none when `AUTH_SECRET` is empty |
| GET | `/auth/oauth/{provider}/start` | `302` to the provider | Authorization code with PKCE `S256`. `redirect_uri` is `<PUBLIC_BASE_URL>/api/auth/oauth/{provider}/callback`. Sets `ragidy_oauth`. Scopes: Google `openid email`, GitHub `user:email`. Errors: `404 not_found` for an unknown or disabled provider |
| GET | `/auth/oauth/{provider}/callback` | `302 <PUBLIC_BASE_URL>/` | The provider redirects here with `code` and `state`. Sets `ragidy_session` like login and clears `ragidy_oauth`. Any failure redirects to `<PUBLIC_BASE_URL>/login?error=oauth_failed`, clears `ragidy_oauth`, and starts no session |
| POST | `/documents` | `202 {id, source, status, error, attempts, created_at}` | Multipart body with one `file` part and no other part. `status` is `pending`. `source` is the filename without its directory, or `upload` when it is empty. Errors: `400`, `401 session_expired`, `409 document_limit_reached`, `413 too_large`, `415 unsupported_type`, `422`, `429 rate_limited`. See [Documents](#documents) |
| POST | `/documents/url` | `202 {id, source, status, error, attempts, created_at}` | Body `{url}`, at most 2048 characters. `status` is `pending`. `source` is the URL as submitted. Errors: as `POST /documents` except `400`, plus `422 url_blocked` and `422 url_fetch_failed` |
| GET | `/documents` | `200 [{id, source, status, error, attempts, created_at}]` | The owner's documents, newest first. `[]` with no cookie, or an unknown or expired one; never creates a guest |
| GET | `/documents/{id}` | `200 {id, source, status, error, attempts, created_at}` | One of the owner's documents, for polling `status` and `error`. Errors: `404 not_found`, `422` |
| POST | `/documents/{id}/retry` | `202 {id, source, status, error, attempts, created_at}` | Queues a `failed` or `ready` document again: `status` `pending`, `attempts` `0`, `error` `null`. Errors: `403 origin_mismatch`, `404 not_found`, `409 document_busy`, `422`, `429 rate_limited`. See [Documents](#documents) |
| POST | `/chats` | `201 {id, title, created_at}` | Body `{title?}`, at most 200 characters, or no body (`title` `null`). Creates a guest and sets `ragidy_guest` when the request has no owner. Errors: `401 session_expired`, `422`, `429 rate_limited` |
| GET | `/chats` | `200 [{id, title, created_at}]` | The owner's chats, newest first. `[]` with no cookie, or an unknown or expired one; never creates a guest |
| GET | `/chats/{id}/messages` | `200 [{role, content, citations}]` | The chat's messages, oldest first. `role` is `user` or `assistant`; `citations` as the `citations` event, `[]` on user messages. Errors: `404 not_found`, `422` |
| POST | `/chats/{id}/messages` | `200 text/event-stream` | Body `{content}`: 1 to 4000 characters after stripping whitespace. Stores the question, then streams the answer. Errors, before the stream: `401 session_expired`, `404 not_found`, `422`, `429 rate_limited`. See [Chats](#chats) |

Add each new endpoint here: method, path, request, response, and error codes.

## Errors
- App errors return `{"code": "<code>", "detail": "<message>"}` with the status code.
- `401 invalid_credentials`: a wrong password, an unknown or malformed email, and an account without a password all get this same response.
- `401 session_expired`: the owner row was deleted (a guest purge or migration) while the request ran. Refresh with `GET /me` and retry.
- `403 origin_mismatch`: every request except GET, HEAD and OPTIONS needs an `Origin` header exactly equal to `PUBLIC_BASE_URL` (CSRF guard). Scripts must send it, for example `curl -H "Origin: http://localhost:5173"`.
- `404 not_found`: the document or chat does not exist, belongs to another owner, or the request has no owner.
- `409 document_busy`: the document is `pending` or `processing`, so a retry would race the worker.
- `409 email_taken`: the email already has an account, including an OAuth-only one.
- `409 document_limit_reached`: the owner already has `MAX_DOCS_<tier>` documents. The detail states the cap.
- `413 too_large`: the file or fetched content is over `UPLOAD_MAX_MB_<tier>`.
- `415 unsupported_type`: the type detected from the bytes is unknown, the file or fetched body is empty or only whitespace, or the type is not in `UPLOAD_TYPES_<tier>`. The detail lists the allowed types.
- `422 url_blocked`: the URL is not http(s), holds credentials (`user:pass@`), or a hop resolves to an address that is not public.
- `422 url_fetch_failed`: a timeout, a connection or DNS error, a malformed host, a non-2xx response, a `Content-Encoding` other than `identity`, or more than 3 redirects.
- `429 rate_limited`: detail `Too many requests; try again later`. `Retry-After` holds the seconds to wait, as an integer. Sources:
  - Guest creation: `GUEST_CREATE_PER_IP_PER_HOUR` per client IP key.
  - Register and login together: `RATE_LIMIT_AUTH_PER_MINUTE` per client IP key.
  - Login lockout: `LOGIN_MAX_FAILURES` attempts per email and client IP key in `LOGIN_FAILURE_WINDOW_MINUTES`. Each attempt counts until one succeeds, which clears that email and IP's count. Once locked, even the right password gets `429`.
  - URL fetches: `URL_FETCH_PER_HOUR` per owner, or per client IP key when the request has no owner yet. Every attempt counts, before the fetch, failed ones included.
  - Document retries: `DOCUMENT_RETRY_PER_HOUR` per owner. Every attempt by an owner counts, before the status check, so a `404` or `409` takes a slot too.
  - Chat messages: `CHAT_MESSAGES_PER_HOUR_<tier>` per owner. The count is taken after the chat lookup, so a `404` takes no slot, and before any LLM call.
- All rate-limit counters are in memory, so they hold only for a single API process.
- Request validation errors keep FastAPI's default `422` body. Free-text fields (`title`, `content`) containing a NUL character (`\u0000`) get `422`. A `POST /documents` without a `file` part gets that body too.
- A malformed multipart body, or one with more than one file or any other part, gets Starlette's `400 {"detail": "<message>"}`, without a `code`.

## Guest cookie
- `ragidy_guest` holds 32 random bytes (`secrets.token_urlsafe(32)`). The DB stores only its SHA-256 hash, in `guests.token`.
- Attributes: `HttpOnly; SameSite=Lax; Path=/; Max-Age=GUEST_TTL_DAYS*86400`, plus `Secure` only when `PUBLIC_BASE_URL` uses `https`.
- The server creates the guest and the cookie on the first write, never on a read.
- One client IP key may create `GUEST_CREATE_PER_IP_PER_HOUR` guests an hour.
- A document write creates the guest only after the body is read, its type checked and its object stored. A `413`, `415` or `422` therefore creates no guest and takes no `GUEST_CREATE_PER_IP_PER_HOUR` slot. A failure after that point still takes the slot, and no guest row is kept.
- Send the first write alone and wait for the `ragidy_guest` cookie before sending parallel writes. Concurrent writes without the cookie each create their own guest, and the last `Set-Cookie` wins.

## Session cookie
- `ragidy_session` holds 32 random bytes, like `ragidy_guest`. The DB stores only its SHA-256 hash, in `sessions.token`.
- Attributes: as `ragidy_guest`, with `Max-Age=SESSION_TTL_DAYS*86400`. No `__Host-` prefix ([ADR 0003](../decisions/0003-guest-and-user-accounts.md) addendum).
- Register, login and the OAuth callback delete the incoming session row and set a new token, so a planted cookie never logs in.
- When the request sends `ragidy_guest`, register, login and the OAuth callback clear it (`Max-Age=0`). In the same transaction, the guest's documents and chats move to the account and the guest is deleted. `MAX_DOCS_USER` is ignored for the move.
- An unknown or expired session cookie counts as no session.

## OAuth
- `ragidy_oauth` holds `{state, verifier, provider, exp}`, HMAC-signed with `AUTH_SECRET`. Attributes: as `ragidy_guest`, with `Max-Age=600`. The callback rejects it once `exp` passes.
- Linking ([ADR 0003](../decisions/0003-guest-and-user-accounts.md)): a known `(provider, provider user id)` signs in its user. Else a verified email that matches a user links to that user, and if that user has a password, the password is removed and its other sessions are deleted. Else a verified email creates a user, and no verified email creates a user without an email.
- GitHub's email is the `/user/emails` entry that is `primary` and `verified`; Google's needs `email_verified`.
- The provider user id must be a non-empty string (GitHub's may also be a number). Any other value fails the callback with `oauth_failed`, so a null or empty id never maps sign-ins to one shared identity.
- The API access log drops the callback query string, so the `code` is never logged. The web container turns off its access and error log for the callback path, and the Vite dev server drops the query from the URL it logs on a proxy error. A failed callback logs a reason code only.

## Documents
- Size: the upload body is read only up to the file limit plus a 16 KiB multipart allowance, and a larger body gets `413` as soon as it passes that. A `Content-Length` over it gets `413` before any read. The file itself may be at most the limit: exactly the limit is accepted.
- Type: decided from the bytes, never the client `Content-Type`. Text is `html` when it starts, after any BOM and whitespace, with `<!doctype html`, `<html`, `<head` or `<body`. Other valid UTF-8 is `txt`, or `md` when the name ends in `.md`: the filename, or for a URL the final URL path after redirects. An empty or whitespace-only body gets `415`.
- Order: the cap check runs and the read transaction is committed before the body is read or the URL fetched. Then the type check, then the object put to `documents/<id>` with the detected MIME type. Only then is a guest created (the first write), the owner row locked `FOR UPDATE`, the cap checked again and the row inserted. Any failure after the put deletes the object.
- URL fetch: http(s) only. Every resolved address of every hop must be public (Python `is_global`, and not multicast, reserved or IPv6 site-local, so NAT64 `64:ff9b::/96` is blocked too; an IPv4-mapped IPv6 address is unwrapped first), else `422 url_blocked`. A URL with credentials (`user:pass@`), submitted or in a redirect, also gets `422 url_blocked`. The API connects to that vetted IP (IPv4 first, one IP tried) with the hostname as `Host` and TLS SNI. It follows at most 3 redirects and checks each hop again. It ignores proxy env vars. The whole fetch, redirects included, has one deadline, `URL_FETCH_TIMEOUT_SECONDS`. It sends `Accept-Encoding: identity` and counts the raw bytes; a response with any other `Content-Encoding` gets `422 url_fetch_failed`.
- Storage: the bucket `S3_BUCKET` is created, private, on the first upload that finds it missing. That create sends no `LocationConstraint`, so on AWS outside `us-east-1` create the bucket first.
- Ingestion: the worker (`make worker`) moves `status` from `pending` through `processing` to `ready` or `failed`. On `failed`, `error` holds a short user-safe message, never the raw exception. Poll `GET /documents/{id}` for the outcome. Retry rules: [overview](../architecture/overview.md#runtime-self-healing-rules).
- Behind the web container (`make up`), nginx accepts bodies up to `6m` on `/api/documents` only; every other route keeps nginx's `1m` default. Raising any `UPLOAD_MAX_MB_*` above 5 needs `client_max_body_size` in `infrastructure/docker/nginx.conf` raised too, above the largest limit plus 16 KiB.
- Accepted risks:
  - A failed URL fetch takes no document slot; `URL_FETCH_PER_HOUR` bounds how often an owner can make the server fetch.

## Chats
- `POST /chats/{id}/messages` checks, in order: the chat lookup (`404`), the hourly limit (`429`), the owner row (`401`). It then stores and commits the question before any LLM call. Any of these errors returns JSON, not a stream, and stores no message.
- Each question is answered on its own; earlier messages are not sent to the model ([ADR 0008](../decisions/0008-chat-streaming-and-history.md)).
- Stream events, in order:
  - `token` `{"text": "<chunk>"}`, repeated. A not-found answer, or a model that does not stream, sends one `token` with the full answer.
  - `citations` `[{document_id, source, page, snippet}]`, once. `page` is `null` when the source has no pages. `[]` when the answer is not found.
  - `done` `{}`, last.
- `error` `{"code": "answer_failed", "detail": "The answer could not be generated; try again later"}` replaces `citations` and `done` when the provider fails or a database error stops the answer from being stored. It may follow `token` events. No assistant message is stored, and the question stays unanswered in the history.
- While the stream is idle, the server sends a `: ping` comment every 15 s to keep it open. `EventSource` clients ignore it.
- The assistant message is stored after the last `token` and before `citations`. If the chat was deleted meanwhile, the stream still ends with `citations` and `done`, and the answer is not stored.
- A client disconnect cancels the answer and stores no assistant message.
