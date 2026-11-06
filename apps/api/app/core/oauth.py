"""OAuth provider entries (ADR 0003): endpoints, scopes and identity mapping; no I/O."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import SecretStr

from app.core.config import Settings


@dataclass(frozen=True)
class Identity:
    provider_user_id: str
    email: str | None
    email_verified: bool


@dataclass(frozen=True)
class OAuthProvider:
    id: str
    name: str
    authorize_url: str
    token_url: str
    scopes: str
    identity_urls: tuple[str, ...]
    # Gets the JSON bodies of identity_urls, in order; may raise KeyError, TypeError, ValueError.
    to_identity: Callable[[list[Any]], Identity]
    # (client id, client secret); see enabled() for when the provider is on.
    credentials: Callable[[Settings], tuple[str, SecretStr]]


def _provider_user_id(value: Any, *, allow_int: bool = False) -> str:
    # A null or empty id would map every such sign-in to one shared identity.
    if isinstance(value, str) and value:
        return value
    if allow_int and isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    raise ValueError("invalid provider id")


def _google_identity(bodies: list[Any]) -> Identity:
    info = bodies[0]
    sub = _provider_user_id(info["sub"])
    return Identity(sub, info.get("email"), info.get("email_verified") is True)


def _github_identity(bodies: list[Any]) -> Identity:
    user, emails = bodies
    primary = next(
        (e for e in emails if e.get("primary") is True and e.get("verified") is True), None
    )
    email = primary["email"] if primary else None
    return Identity(_provider_user_id(user["id"], allow_int=True), email, email is not None)


PROVIDERS: dict[str, OAuthProvider] = {
    "google": OAuthProvider(
        id="google",
        name="Google",
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        token_url="https://oauth2.googleapis.com/token",
        scopes="openid email",
        identity_urls=("https://openidconnect.googleapis.com/v1/userinfo",),
        to_identity=_google_identity,
        credentials=lambda s: (s.oauth_google_client_id, s.oauth_google_client_secret),
    ),
    "github": OAuthProvider(
        id="github",
        name="GitHub",
        authorize_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        scopes="user:email",
        identity_urls=("https://api.github.com/user", "https://api.github.com/user/emails"),
        to_identity=_github_identity,
        credentials=lambda s: (s.oauth_github_client_id, s.oauth_github_client_secret),
    ),
}


def enabled(settings: Settings) -> list[OAuthProvider]:
    """Providers with a client id, when AUTH_SECRET is set to sign the state cookie."""
    if not settings.auth_secret.get_secret_value():
        return []
    return [p for p in PROVIDERS.values() if p.credentials(settings)[0]]
