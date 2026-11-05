from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_db
from app.services.owners import CurrentOwner, create_guest, resolve_guest
from app.services.rate_limit import ip_key

GUEST_COOKIE = "ragidy_guest"

DbSession = Annotated[AsyncSession, Depends(get_db)]


def client_ip_key(request: Request) -> str:
    # ProxyHeadersMiddleware rewrites the peer to the forwarded client for trusted proxies only.
    return ip_key(request.client.host if request.client else None)


async def current_owner(request: Request, db: DbSession) -> CurrentOwner | None:
    # ragidy_session resolution arrives with accounts (step 7).
    return await resolve_guest(db, request.cookies.get(GUEST_COOKIE))


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
    settings = get_settings()
    response.set_cookie(
        GUEST_COOKIE,
        token,
        max_age=settings.guest_ttl_days * 86400,
        path="/",
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return owner


WriteOwner = Annotated[CurrentOwner, Depends(write_owner)]
