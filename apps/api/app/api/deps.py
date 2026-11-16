from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.services.owners import CurrentOwner, create_guest, resolve_guest, resolve_session
from app.services.rate_limit import ip_key

GUEST_COOKIE = "ragidy_guest"
SESSION_COOKIE = "ragidy_session"
OAUTH_COOKIE = "ragidy_oauth"

DbSession = Annotated[AsyncSession, Depends(get_db)]


def set_cookie(response: Response, name: str, value: str, max_age: int) -> None:
    """Set a cookie with the attributes every Ragidy cookie shares (requirements, Tiers)."""
    response.set_cookie(
        name,
        value,
        max_age=max_age,
        path="/",
        secure=get_settings().cookie_secure,
        httponly=True,
        samesite="lax",
    )


def clear_cookie(response: Response, name: str) -> None:
    set_cookie(response, name, "", 0)


def client_ip_key(request: Request) -> str:
    # ProxyHeadersMiddleware rewrites the peer to the forwarded client for trusted proxies only.
    return ip_key(request.client.host if request.client else None)


async def current_owner(request: Request, db: DbSession) -> CurrentOwner | None:
    """The session's user, else the cookie's guest; unknown or expired cookies are no cookie."""
    owner = await resolve_session(db, request.cookies.get(SESSION_COOKIE))
    return owner or await resolve_guest(db, request.cookies.get(GUEST_COOKIE))


ReadOwner = Annotated[CurrentOwner | None, Depends(current_owner)]


async def write_owner(
    request: Request, response: Response, db: DbSession, owner: ReadOwner
) -> CurrentOwner:
    """The owner of a write; creates a guest (flush only) and its cookie when there is none.

    The write's service commits once. On error the handler builds a fresh response, so a
    failed write leaves neither a guest row nor a Set-Cookie.
    Routes using WriteOwner must return models or dicts, never a Response object: FastAPI
    then drops this dependency's Set-Cookie while the service still commits the guest
    (or the route must copy the cookie onto its own response).
    """
    if owner is not None:
        return owner
    owner, token = await create_guest(db, client_ip_key(request))
    set_cookie(response, GUEST_COOKIE, token, get_settings().guest_ttl_days * 86400)
    return owner


WriteOwner = Annotated[CurrentOwner, Depends(write_owner)]
