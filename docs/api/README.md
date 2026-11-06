# API

Base URL in development: `http://localhost:8000`. FastAPI serves interactive docs at `/docs` and the OpenAPI schema at `/openapi.json`.

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

Add each new endpoint here: method, path, request, response, and error codes.

## Errors
- App errors return `{"code": "<code>", "detail": "<message>"}` with the status code.
- `401 invalid_credentials`: a wrong password, an unknown or malformed email, and an account without a password all get this same response.
- `403 origin_mismatch`: every request except GET, HEAD and OPTIONS needs an `Origin` header exactly equal to `PUBLIC_BASE_URL` (CSRF guard). Scripts must send it, for example `curl -H "Origin: http://localhost:5173"`.
- `409 email_taken`: the email already has an account, including an OAuth-only one.
- `429 rate_limited`: detail `Too many requests; try again later`. `Retry-After` holds the seconds to wait, as an integer. Sources:
  - Guest creation: `GUEST_CREATE_PER_IP_PER_HOUR` per client IP key.
  - Register and login together: `RATE_LIMIT_AUTH_PER_MINUTE` per client IP key.
  - Login lockout: `LOGIN_MAX_FAILURES` attempts per email and client IP key in `LOGIN_FAILURE_WINDOW_MINUTES`. Each attempt counts until one succeeds, which clears that email and IP's count. Once locked, even the right password gets `429`.
- All rate-limit counters are in memory, so they hold only for a single API process.
- Request validation errors keep FastAPI's default `422` body.

## Guest cookie
- `ragidy_guest` holds 32 random bytes (`secrets.token_urlsafe(32)`). The DB stores only its SHA-256 hash, in `guests.token`.
- Attributes: `HttpOnly; SameSite=Lax; Path=/; Max-Age=GUEST_TTL_DAYS*86400`, plus `Secure` only when `PUBLIC_BASE_URL` uses `https`.
- The server creates the guest and the cookie on the first write, never on a read.
- One client IP key may create `GUEST_CREATE_PER_IP_PER_HOUR` guests an hour.
- A failed first write (`422`, `413`, `415`, `409`, and so on) still counts against `GUEST_CREATE_PER_IP_PER_HOUR`, because the slot is taken before the write runs. No guest row is kept.
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
- The API access log drops the callback query string, so the `code` is never logged. A failed callback logs a reason code only.
