"""Guest purge (ADR 0009, R10, R14): delete expired guests with their objects and rows.

Runs inside the ingestion worker. One transaction per guest; a failure rolls back that guest only.
"""

import logging
from uuid import UUID

from botocore.exceptions import BotoCoreError, ClientError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import storage
from app.core.db import get_sessionmaker
from app.repositories import owners, purge

logger = logging.getLogger(__name__)

PURGE_INTERVAL_SECONDS = 900
PURGE_BATCH = 100


async def purge_expired() -> int:
    """Purge up to PURGE_BATCH expired guests; return how many (PURGE_BATCH means more are due).

    A store-down error (BotoCoreError or an S3 5xx) stops the batch; the return is the count purged
    so far. An S3 4xx (AccessDenied, object lock) skips that guest, not the rest of the batch.
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        owner_ids = await purge.expired_guest_owner_ids(db, PURGE_BATCH)
        await db.commit()
    purged = 0
    for owner_id in owner_ids:
        try:
            async with sessionmaker() as db:
                if await _purge_guest(db, owner_id):
                    purged += 1
        except (BotoCoreError, ClientError) as exc:
            if not isinstance(exc, ClientError) or _store_down(exc):
                logger.warning(
                    "Purge stopped at owner %s: store down (%s)", owner_id, type(exc).__name__
                )
                break
            # Fixed AWS error code only: never the message or the key.
            logger.warning(
                "Purge failed for owner %s (%s %s)",
                owner_id,
                type(exc).__name__,
                exc.response.get("Error", {}).get("Code", "unknown"),
            )
        except Exception as exc:
            # Type only: exception text can echo a source URL or an S3 key.
            logger.warning("Purge failed for owner %s (%s)", owner_id, type(exc).__name__)
    async with sessionmaker() as db:
        sessions = await purge.delete_expired_sessions(db)
        await db.commit()
    logger.info("Purged %d of %d expired guests and %d sessions", purged, len(owner_ids), sessions)
    return purged


def _store_down(exc: ClientError) -> bool:
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    return not isinstance(status, int) or status >= 500


async def _purge_guest(db: AsyncSession, owner_id: UUID) -> bool:
    # Exiting the session without commit rolls back, so an error undoes this guest only.
    if not await owners.lock_owner(db, owner_id) or not await purge.guest_expired(db, owner_id):
        return False
    for document_id in await purge.owner_document_ids(db, owner_id):
        await storage.delete_object(storage.document_key(document_id))
    await purge.delete_owned_rows(db, owner_id)
    await owners.delete_owner(db, owner_id)
    await db.commit()
    return True
