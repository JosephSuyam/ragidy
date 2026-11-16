import base64
import hashlib
import hmac
import json
import secrets
import time
from typing import Any


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def sign(payload: dict[str, Any], secret: str) -> str:
    """`payload` as URL-safe `<base64url JSON>.<base64url HMAC-SHA256>`; set `exp` (unix s)."""
    body = _b64encode(json.dumps(payload, separators=(",", ":")).encode())
    return f"{body}.{_signature(body, secret)}"


def unsign(value: str, secret: str) -> dict[str, Any] | None:
    """The payload of a `sign` value; None when tampered, malformed, expired or without `exp`."""
    body, _, signature = value.rpartition(".")
    if not hmac.compare_digest(signature.encode(), _signature(body, secret).encode()):
        return None
    try:
        payload = json.loads(_b64decode(body))
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    exp = payload.get("exp")
    if not isinstance(exp, int | float) or exp <= time.time():
        return None
    return payload


def _signature(body: str, secret: str) -> str:
    return _b64encode(hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest())


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
