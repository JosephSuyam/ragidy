from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from app.api.deps import (
    GUEST_COOKIE,
    OAUTH_COOKIE,
    SESSION_COOKIE,
    DbSession,
    clear_cookie,
    client_ip_key,
    set_cookie,
)
from app.core.config import get_settings
from app.schemas.auth import LoginRequest, ProviderResponse, RegisterRequest, UserResponse
from app.services import auth, oauth

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", status_code=201)
async def register(
    body: RegisterRequest, request: Request, response: Response, db: DbSession
) -> UserResponse:
    user, token = await auth.register(
        db,
        body.email,
        body.password,
        ip_key=client_ip_key(request),
        session_token=request.cookies.get(SESSION_COOKIE),
        guest_token=request.cookies.get(GUEST_COOKIE),
    )
    _set_session_cookies(request, response, token)
    return UserResponse.model_validate(user)


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response, db: DbSession
) -> UserResponse:
    user, token = await auth.login(
        db,
        body.email,
        body.password,
        ip_key=client_ip_key(request),
        session_token=request.cookies.get(SESSION_COOKIE),
        guest_token=request.cookies.get(GUEST_COOKIE),
    )
    _set_session_cookies(request, response, token)
    return UserResponse.model_validate(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: DbSession) -> None:
    await auth.logout(db, request.cookies.get(SESSION_COOKIE))
    clear_cookie(response, SESSION_COOKIE)


@router.get("/providers")
async def providers() -> list[ProviderResponse]:
    return [ProviderResponse.model_validate(p) for p in oauth.providers()]


@router.get("/oauth/{provider}/start")
async def oauth_start(provider: str) -> RedirectResponse:
    url, cookie = oauth.start(provider)
    response = RedirectResponse(url, status_code=302)
    set_cookie(response, OAUTH_COOKIE, cookie, oauth.COOKIE_TTL_SECONDS)
    return response


@router.get("/oauth/{provider}/callback")
async def oauth_callback(
    provider: str,
    request: Request,
    db: DbSession,
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> RedirectResponse:
    token = await oauth.callback(
        db,
        provider,
        None if error else code,
        state,
        request.cookies.get(OAUTH_COOKIE),
        session_token=request.cookies.get(SESSION_COOKIE),
        guest_token=request.cookies.get(GUEST_COOKIE),
    )
    base_url = get_settings().public_base_url
    response = RedirectResponse(
        f"{base_url}/" if token else f"{base_url}/login?error=oauth_failed", status_code=302
    )
    clear_cookie(response, OAUTH_COOKIE)
    if token:
        _set_session_cookies(request, response, token)
    return response


def _set_session_cookies(request: Request, response: Response, token: str) -> None:
    set_cookie(response, SESSION_COOKIE, token, get_settings().session_ttl_days * 86400)
    if GUEST_COOKIE in request.cookies:
        clear_cookie(response, GUEST_COOKIE)
