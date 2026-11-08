# 0010: Web client

- Status: accepted
- Date: 2026-11-08
- Related: [0003](0003-guest-and-user-accounts.md) (guest cookie, sessions), [0008](0008-chat-streaming-and-history.md) (SSE events), [0009](0009-deletion-and-purge.md) (dangling citations)

## Context
MVP step 13 builds the React client in `apps/web` on the existing API: auth, uploads, document status, chats and streamed answers. It needs TypeScript types for the API, two pages, four reads, and one POST that streams SSE. Answers, snippets and citation `source` values come from uploads and the LLM, so they are untrusted. The server creates a guest on the first write, and concurrent cookieless writes each create their own guest (`docs/api/README.md`). `OriginMiddleware` rejects any write whose `Origin` differs from `PUBLIC_BASE_URL`.

## Decision
- **Shared types are generated from OpenAPI.**
  - `packages/shared-types/openapi.json` is a committed dump of FastAPI `app.openapi()`.
  - `packages/shared-types/api.d.ts` is generated from it by `openapi-typescript`. The generator is a nested npm package in `packages/shared-types`: exact-pinned `openapi-typescript` and `typescript@5`, with its own lockfile. Only `make types` installs it; CI and the Docker build use the committed files.
  - `packages/shared-types/index.ts` hand-writes what OpenAPI cannot express: `ApiErrorBody {code, detail}`, `ValidationErrorBody`, and `ChatStreamEvent`, a union of `token {text}`, `citations CitationOut[]`, `done {}` and `error {code: 'answer_failed', detail}`.
  - `make types` regenerates both files. An API pytest snapshot test fails the gate when `app.openapi()` differs from `openapi.json`. The web app imports through the `@shared/*` alias.
- **Schemas tightened for the generator:** `DocumentOut.status` becomes `Literal["pending","processing","ready","failed"]` and `MessageOut.role` becomes `Literal["user","assistant"]`. The wire format does not change.
- **Routing:** a hand-written `pathname` switch for `/` and `/login`, plus a `navigate()` helper on `history.pushState` and a `popstate` listener.
- **Data fetching:** plain `fetch` hooks.
  - `/me` lives in a session context. Inside `SessionProvider`, the `Router` is keyed by `sessionVersion`, which bumps when the owner changes (login, logout, session expiry), so the remount drops stale state.
  - `GET /documents` polls every 2 s, only while a document is `pending` or `processing`.
  - `AbortController` guards each read against races and unmounts.
- **Streaming:** `EventSource` cannot POST, so `src/services/sse.ts` is a ~30-line `fetch` `ReadableStream` SSE parser. It handles LF and CRLF and multi-line `data:`, and ignores comment lines such as `: ping`.
- **Session state is an expiry, not a flag:** a user has no client-side expiry; a guest trusts its session until `guest_expires_at` minus 60 s of clock skew; no `/me` session means none. Logout clears the state before its POST.
- **First-write gate:** with no trusted session, the API client sends the first write alone and holds the others until it resolves. It then refetches `/me` once to learn the guest expiry, updating state without a remount. Uploads always go one at a time.
- **Other tabs:** on `visibilitychange` to visible, the client refetches `/me` and remounts only if the owner identity changed (sign-in or sign-out in another tab). `/me` has no owner id, so identity is `tier`, `email` and `guest_expires_at`.
- **Session expiry:** concurrent `401 session_expired` responses share one `/me` refetch and one remount; each request then retries once through the gate. A view the remount unmounts aborts its requests, so an id-scoped request (a message to a purged guest's chat) is dropped, not retried under the new owner. This refines ADR 0003's "the client refreshes its session state and retries".
- **Untrusted content is text only.** Never use `dangerouslySetInnerHTML`. Answers render as plain text with `whitespace-pre-wrap`, with no markdown renderer. A citation `source` becomes a link only when `new URL(source).protocol` is `http:` or `https:`. A citation whose `document_id` no longer exists still renders from its stored `source` and `snippet`.
- **StrictMode:** dev double-runs effects, so effects only read. Only user actions send writes.
- **Dev host:** open the app at `localhost`, never `127.0.0.1`, or `OriginMiddleware` returns `403 origin_mismatch`.

## Alternatives
- **Hand-written TS mirror of the schemas:** no tooling, but drift is caught only by review.
- **Generator as an `apps/web` devDependency:** `openapi-typescript` has peer `typescript ^5.x` and uses its JS compiler API; `apps/web` uses TypeScript 7 (Go port, no JS API).
- **Pinned `npx openapi-typescript@7.13.0` with no lockfile:** no extra package, but its transitive dependencies are unlocked.
- **`react-router`:** a new runtime dependency for 2 routes. Revisit when deep links such as `/chats/:id` are needed.
- **TanStack Query:** a new runtime dependency whose retry and refocus defaults need tuning for 4 reads. Revisit if screens grow.
- **`EventSource`:** GET only, and it cannot send the request body.
- **A markdown renderer for answers:** nicer output, but a new dependency and an HTML-injection surface for LLM text.
- **Parallel cookieless writes:** each creates an orphan guest, and the last `Set-Cookie` wins.

## Consequences
- No new dependency in `apps/web`. The generator lives in `packages/shared-types` with its own `node_modules` and lockfile, so the repo has a second npm lockfile to keep updated.
- Any API schema change must run `make types`, or the gate fails on the snapshot test.
- No deep links: a reload always lands on `/` or `/login`.
- Answers show markdown syntax as raw text.
- A user session that ends server-side (expiry, or sign-out in a side-by-side visible window) is noticed only at the next `/me` (visibility change, `session_expired`, reload). The API treats an expired or unknown `ragidy_session` as no cookie, so a write in that window creates a guest (not `401`), and parallel writes create orphan guests.
- Deferred: `react-router`, TanStack Query, markdown rendering, `Last-Event-ID` resume, parallel uploads, `features/workspaces`.
