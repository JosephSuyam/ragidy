from fastapi import APIRouter, Request, Response

from app.api.deps import (
    GUEST_COOKIE,
    SESSION_COOKIE,
    DbSession,
    clear_cookie,
    client_ip_key,
    set_cookie,
)
from app.core.config import get_settings
from app.schemas.auth import LoginRequest, RegisterRequest, UserResponse
from app.services import auth

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


def _set_session_cookies(request: Request, response: Response, token: str) -> None:
    set_cookie(response, SESSION_COOKIE, token, get_settings().session_ttl_days * 86400)
    if GUEST_COOKIE in request.cookies:
        clear_cookie(response, GUEST_COOKIE)
