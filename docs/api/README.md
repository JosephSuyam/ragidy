# API

Base URL in development: `http://localhost:8000`. FastAPI serves interactive docs at `/docs` and the OpenAPI schema at `/openapi.json`.

| Method | Path | Response | Notes |
|---|---|---|---|
| GET | `/health` | `{"status": "ok"}` | Liveness check |
| GET | `/me` | `200 {tier, email, limits: {max_upload_mb, upload_types, max_docs, chat_messages_per_hour}, document_count, guest_expires_at}` | The owner's tier and limits. With no cookie, or an unknown or expired one: `tier` is `guest`, `email` and `guest_expires_at` are `null`, `document_count` is `0`, and no row is written |

Add each new endpoint here: method, path, request, response, and error codes.

## Errors
- App errors return `{"code": "<code>", "detail": "<message>"}` with the status code.
- `429 rate_limited`: too many guests created from one client IP. `Retry-After` holds the seconds to wait, as an integer.
- Request validation errors keep FastAPI's default `422` body.

## Guest cookie
- `ragidy_guest` holds 32 random bytes (`secrets.token_urlsafe(32)`). The DB stores only its SHA-256 hash, in `guests.token`.
- Attributes: `HttpOnly; SameSite=Lax; Path=/; Max-Age=GUEST_TTL_DAYS*86400`, plus `Secure` only when `PUBLIC_BASE_URL` uses `https`.
- The server creates the guest and the cookie on the first write, never on a read.
- One client IP key may create `GUEST_CREATE_PER_IP_PER_HOUR` guests an hour. The counter is in memory, so it holds only for a single API process.
- A failed first write (`422`, `413`, `415`, `409`, and so on) still counts against `GUEST_CREATE_PER_IP_PER_HOUR`, because the slot is taken before the write runs. No guest row is kept.
- Send the first write alone and wait for the `ragidy_guest` cookie before sending parallel writes. Concurrent writes without the cookie each create their own guest, and the last `Set-Cookie` wins.
