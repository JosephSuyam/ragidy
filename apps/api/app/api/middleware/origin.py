from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class OriginMiddleware:
    """Rejects unsafe-method requests whose Origin is not PUBLIC_BASE_URL (CSRF guard).

    Pure ASGI, so streamed responses pass through untouched.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] == "http"
            and scope["method"] not in _SAFE_METHODS
            and Headers(scope=scope).get("origin") != get_settings().public_base_url
        ):
            # AppError's handler sits inside user middleware, so answer here.
            response = JSONResponse(
                {"code": "origin_mismatch", "detail": "Request origin is not allowed"},
                status_code=403,
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)
