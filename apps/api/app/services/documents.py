from collections.abc import Awaitable, Callable
from contextlib import suppress
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.config import TierLimits, get_settings
from app.core.errors import AppError
from app.core.filetypes import MIME_TYPES, detect_type
from app.models.documents import Document
from app.repositories.documents import count_documents, insert_document
from app.services.owners import CurrentOwner, lock_write_owner
from app.services.rate_limit import rate_limited, url_fetches
from app.services.url_fetch import fetch_url


def upload_limits(owner: CurrentOwner | None) -> tuple[TierLimits, int]:
    """The owner's tier limits and its max upload size in bytes; no owner is a guest."""
    settings = get_settings()
    if owner is None or owner.tier == "guest":
        return settings.limits("guest"), settings.upload_max_bytes_guest
    return settings.limits("user"), settings.upload_max_bytes_user


async def check_cap(db: AsyncSession, owner: CurrentOwner | None, max_docs: int) -> None:
    """409 when the owner is at its document cap, then end the read transaction.

    Committing returns the connection to the pool before the slow upload read or URL fetch.
    """
    if owner is not None:
        await _ensure_below_cap(db, owner.owner_id, max_docs)
    await db.commit()


async def fetch_document_url(url: str, rate_key: str, max_bytes: int) -> tuple[bytes, str]:
    """Fetch `url` for a document; return the body and the final URL's path for type detection.

    Every attempt counts against URL_FETCH_PER_HOUR for `rate_key`, before the fetch.
    """
    retry_after = url_fetches.hit(rate_key, get_settings().url_fetch_per_hour)
    if retry_after is not None:
        raise rate_limited(retry_after)
    body, final_url = await fetch_url(url, max_bytes)
    return body, urlsplit(final_url).path


def content_type(data: bytes, name: str, limits: TierLimits) -> str:
    """The MIME type of `data`; 415 when it is unknown or not allowed for the tier."""
    kind = detect_type(data, name)
    if kind is None or kind not in limits.upload_types:
        allowed = ", ".join(limits.upload_types)
        raise AppError(415, "unsupported_type", f"Unsupported file type; allowed: {allowed}")
    return MIME_TYPES[kind]


async def create_document(
    db: AsyncSession,
    data: bytes,
    mime: str,
    source: str,
    max_docs: int,
    get_owner: Callable[[], Awaitable[CurrentOwner]],
) -> Document:
    """Store the object, then insert the pending row and commit (ADR 0002).

    `get_owner` runs only after the object is stored, so a guest is created only for a valid
    body and no transaction stays open during the S3 write. Any failure after the put deletes
    the object.
    """
    id = uuid4()
    key = f"documents/{id}"
    await storage.put_object(key, data, mime)
    try:
        owner = await get_owner()
        await lock_write_owner(db, owner)
        await _ensure_below_cap(db, owner.owner_id, max_docs)
        doc = await insert_document(db, id, owner.owner_id, source, get_settings().embed_model)
        await db.commit()
    except BaseException:
        # Best effort: a failed delete must not mask the original error.
        with suppress(Exception):
            await storage.delete_object(key)
        raise
    return doc


async def _ensure_below_cap(db: AsyncSession, owner_id: UUID, max_docs: int) -> None:
    if await count_documents(db, owner_id) >= max_docs:
        raise AppError(409, "document_limit_reached", f"You can keep at most {max_docs} documents")
