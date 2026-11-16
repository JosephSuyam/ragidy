"""Ingestion worker: claims pending documents, embeds them and stores their chunks (ADR 0002).

Run one instance with `python -m app.workers.ingestion`; a Postgres advisory lock refuses a second.
"""

import asyncio
import logging
import time
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.exc import OperationalError

from app.core import storage
from app.core.config import get_settings
from app.core.db import get_engine, get_sessionmaker
from app.core.logging import configure_logging
from app.models.documents import Document
from app.rag.errors import IngestionError
from app.rag.ingestion import ingest_document
from app.repositories import document_jobs
from app.repositories.vector.chunks import replace_chunks
from app.workers.purge import PURGE_BATCH, PURGE_INTERVAL_SECONDS, purge_expired

logger = logging.getLogger(__name__)

POLL_SECONDS = 2
JOB_TIMEOUT_SECONDS = 600


def backoff(attempts: int) -> timedelta:
    """Delay before the next attempt: 30 s after the first failure, then 2 min."""
    return timedelta(seconds=30 * 4 ** (attempts - 1))


async def run_once() -> bool:
    """Claim and process one due job; False when none is due.

    No session stays open during the S3 read, parse or embed, so the pool is never held.
    """
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as db:
        doc = await document_jobs.claim_next(db)
        await db.commit()
    if doc is None:
        return False
    try:
        async with asyncio.timeout(JOB_TIMEOUT_SECONDS):
            data, mime = await storage.get_object(storage.document_key(doc.id))
            chunks = await ingest_document(data, mime, doc.source)
        # One transaction, so a crash never leaves a ready document without chunks.
        async with sessionmaker() as db:
            await replace_chunks(db, doc.id, chunks)
            await document_jobs.mark_ready(db, doc.id, get_settings().embed_model)
            await db.commit()
        logger.info("Document %s ready with %d chunks", doc.id, len(chunks))
    except Exception as exc:
        # Never log the source (a URL query can hold tokens) or the embed model (it holds the key).
        logger.exception("Ingestion failed for document %s, attempt %d", doc.id, doc.attempts)
        await _record_failure(doc, exc)
    return True


async def _record_failure(doc: Document, exc: Exception) -> None:
    error = _user_error(exc)
    async with get_sessionmaker()() as db:
        # IngestionError means the input itself is unusable, so a retry cannot help.
        if isinstance(exc, IngestionError) or doc.attempts >= document_jobs.MAX_ATTEMPTS:
            await document_jobs.mark_failed(db, doc.id, error)
        else:
            await document_jobs.requeue(db, doc.id, error, backoff(doc.attempts))
        await db.commit()


def _user_error(exc: Exception) -> str:
    """The text users see in documents.error; only IngestionError messages are user-safe."""
    if isinstance(exc, IngestionError):
        return str(exc) or "Ingestion failed."
    if isinstance(exc, TimeoutError):
        return "Ingestion timed out."
    return "Ingestion failed."


async def main() -> None:
    """Run the worker for good: reconnect and re-take the lock whenever the database drops."""
    configure_logging()
    while True:
        try:
            await _run_locked()
        except OperationalError as exc:
            logger.warning(
                "Ingestion worker lost the database (%s); retrying in %d s", exc, POLL_SECONDS
            )
            await asyncio.sleep(POLL_SECONDS)


async def _run_locked() -> None:
    """Hold the worker lock and process jobs; raise when the lock connection fails."""
    # The advisory lock lives as long as this connection, so keep it open while processing.
    async with get_engine().connect() as lock_conn:
        locked = await document_jobs.try_worker_lock(lock_conn)
        # End the transaction so the lock connection never idles in one.
        await lock_conn.commit()
        if not locked:
            logger.error("Another ingestion worker holds the lock; exiting")
            raise SystemExit(1)
        logger.info("Ingestion worker lock acquired")
        async with get_sessionmaker()() as db:
            count = await document_jobs.reset_interrupted(db)
            await db.commit()
        logger.info("Reset %d interrupted documents", count)
        purge_due_at = time.monotonic()
        while True:
            # A dropped lock connection frees the lock, so never claim a job without it.
            await lock_conn.scalar(select(1))
            await lock_conn.commit()
            if time.monotonic() >= purge_due_at:
                purge_due_at = time.monotonic() + PURGE_INTERVAL_SECONDS
                try:
                    if await purge_expired() == PURGE_BATCH:
                        purge_due_at = time.monotonic()
                except Exception as exc:
                    logger.warning("Guest purge failed (%s)", type(exc).__name__)
            try:
                busy = await run_once()
            except Exception:
                logger.exception("Ingestion worker loop failed; retrying in %d s", POLL_SECONDS)
                busy = False
            if not busy:
                await asyncio.sleep(POLL_SECONDS)


if __name__ == "__main__":
    # psycopg async refuses the default ProactorEventLoop on Windows.
    asyncio.run(main(), loop_factory=asyncio.SelectorEventLoop)
