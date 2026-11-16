from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.middleware.origin import OriginMiddleware
from app.api.routes import auth, chats, documents, health, me
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging

configure_logging()
app = FastAPI(title="Ragidy")
app.add_middleware(OriginMiddleware)
# Settings already holds TRUSTED_PROXIES as network strings; an empty list trusts no proxy.
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=get_settings().trusted_proxies)


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        {"code": exc.code, "detail": exc.detail}, status_code=exc.status, headers=exc.headers
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    # FastAPI's default body echoes each error's `input` (passwords, questions) and `ctx`.
    detail = [{"type": e["type"], "loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]
    return JSONResponse({"detail": detail}, status_code=422)


app.include_router(auth.router)
app.include_router(chats.router)
app.include_router(documents.router)
app.include_router(health.router)
app.include_router(me.router)
