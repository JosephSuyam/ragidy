import logging
import re

# The OAuth callback query holds the authorization code, which logs must never contain.
# GitHub accepts any redirect_uri under the registered one, so match callback subpaths too.
_OAUTH_CALLBACK = re.compile(r"^((?:/api)?/auth/oauth/[^/?]+/callback[^?]*)\?.*$")


class _StripOAuthQuery(logging.Filter):
    """Drop the query from OAuth callback paths in uvicorn access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        # uvicorn.access args: (client_addr, method, full_path, http_version, status_code)
        args = record.args
        if isinstance(args, tuple) and len(args) == 5 and isinstance(args[2], str):
            record.args = (*args[:2], _OAUTH_CALLBACK.sub(r"\1", args[2]), *args[3:])
        return True


def configure_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("uvicorn.access").addFilter(_StripOAuthQuery())
