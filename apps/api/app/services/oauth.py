"""OAuth sign-in (R4, ADR 0003): authorization code with PKCE S256 and a signed state cookie."""

import base64
import hashlib
import hmac
import logging
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.core.oauth import Identity, OAuthProvider, enabled
from app.models.accounts import User
from app.repositories import sessions, users
from app.services.auth import normalize_email, start_session
from app.services.tokens import new_token, sign, unsign

COOKIE_TTL_SECONDS = 600

logger = logging.getLogger(__name__)


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=10)


def providers() -> list[OAuthProvider]:
    return enabled(get_settings())


def start(provider_id: str) -> tuple[str, str]:
    """The provider's authorize URL and the signed `ragidy_oauth` cookie value."""
    provider = _enabled_provider(provider_id)
    if provider is None:
        raise AppError(404, "not_found", "Unknown sign-in provider")
    state, verifier = new_token(), new_token()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
    query = urlencode(
        {
            "response_type": "code",
            "client_id": provider.credentials(get_settings())[0],
            "redirect_uri": _redirect_uri(provider_id),
            "scope": provider.scopes,
            "state": state,
            "code_challenge": challenge.rstrip(b"=").decode(),
            "code_challenge_method": "S256",
        }
    )
    payload = {
        "state": state,
        "verifier": verifier,
        "provider": provider_id,
        "exp": int(time.time()) + COOKIE_TTL_SECONDS,
    }
    return f"{provider.authorize_url}?{query}", sign(payload, _secret())


async def callback(
    db: AsyncSession,
    provider_id: str,
    code: str | None,
    state: str | None,
    cookie: str | None,
    *,
    session_token: str | None,
    guest_token: str | None,
) -> str | None:
    """Sign in with the provider's identity; the raw session token, or None on any failure.

    A failure logs a reason code only, never codes, tokens or provider responses.
    """
    try:
        return await _sign_in(db, provider_id, code, state, cookie, session_token, guest_token)
    except _Failed as exc:
        logger.warning("oauth callback failed: %s", exc)
        return None


class _Failed(Exception):
    """A callback failure; its message is a reason code, safe to log."""


async def _sign_in(
    db: AsyncSession,
    provider_id: str,
    code: str | None,
    state: str | None,
    cookie: str | None,
    session_token: str | None,
    guest_token: str | None,
) -> str:
    provider = _enabled_provider(provider_id)
    payload = unsign(cookie, _secret()) if cookie and provider else None
    if provider is None or payload is None or not code or not state:
        raise _Failed("bad_request")
    expected = payload.get("state")
    if payload.get("provider") != provider_id or not isinstance(expected, str):
        raise _Failed("bad_cookie")
    if not hmac.compare_digest(expected.encode(), state.encode()):
        raise _Failed("state_mismatch")
    try:
        identity = await _fetch_identity(provider, code, str(payload.get("verifier")))
        verified = identity.email if identity.email_verified else None
        email = normalize_email(verified) if verified else None
    except (httpx.HTTPError, ValueError, KeyError, TypeError, AttributeError) as exc:
        # The class name only: httpx exceptions carry the request, and bodies may hold tokens.
        raise _Failed(f"provider_failed:{type(exc).__name__}") from None
    try:
        user = await _link(db, provider_id, identity.provider_user_id, email)
        token = await start_session(db, user, session_token, guest_token)
        await db.commit()
    except IntegrityError:  # a concurrent sign-in won the identity or the email
        await db.rollback()
        raise _Failed("conflict") from None
    return token


async def _fetch_identity(provider: OAuthProvider, code: str, verifier: str) -> Identity:
    client_id, client_secret = provider.credentials(get_settings())
    async with _http() as http:
        response = await http.post(
            provider.token_url,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _redirect_uri(provider.id),
                "client_id": client_id,
                "client_secret": client_secret.get_secret_value(),
                "code_verifier": verifier,
            },
            # GitHub answers form-encoded without it.
            headers={"Accept": "application/json"},
        )
        response.raise_for_status()
        access_token = response.json().get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ValueError("no access token")  # GitHub reports errors with a 200
        headers = {"Accept": "application/json", "Authorization": f"Bearer {access_token}"}
        bodies: list[Any] = []
        for url in provider.identity_urls:
            response = await http.get(url, headers=headers)
            response.raise_for_status()
            bodies.append(response.json())
    return provider.to_identity(bodies)


async def _link(
    db: AsyncSession, provider_id: str, provider_user_id: str, email: str | None
) -> User:
    """The user of this identity per the ADR 0003 linking rule; flush only."""
    user = await users.get_user_by_identity(db, provider_id, provider_user_id)
    if user is not None:
        return user
    user = await users.get_user_by_email(db, email) if email else None
    if user is None:
        user = await users.create_user(db, email, None)
    elif user.password is not None:
        # Email registration is unverified, so the password and its sessions may be a squatter's.
        await users.set_password(db, user.id, None)
        await sessions.delete_user_sessions(db, user.id)
    await users.add_identity(db, user.id, provider_id, provider_user_id)
    return user


def _enabled_provider(provider_id: str) -> OAuthProvider | None:
    return next((p for p in providers() if p.id == provider_id), None)


def _secret() -> str:
    return get_settings().auth_secret.get_secret_value()


def _redirect_uri(provider_id: str) -> str:
    return f"{get_settings().public_base_url}/api/auth/oauth/{provider_id}/callback"
