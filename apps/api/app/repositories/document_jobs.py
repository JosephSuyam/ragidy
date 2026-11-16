"""Ingestion job queue on the documents table (ADR 0002).

Worker-only and not owner-filtered: only app/workers calls it. Flush only, the caller commits.
"""

from datetime import timedelta
from typing import Any, cast
from uuid import UUID

from sqlalchemy import CursorResult, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncSession

from app.models.documents import Document

MAX_ATTEMPTS = 3
WORKER_LOCK_KEY = 7_261_676_964  # arbitrary, unique to the ingestion worker


async def reset_interrupted(db: AsyncSession) -> int:
    """Fail rows that crashed during their last attempt; return every other one to pending."""
    last_attempt = Document.attempts >= MAX_ATTEMPTS
    stmt = (
        update(Document)
        .where(Document.status == "processing")
        .values(
            status=case((last_attempt, "failed"), else_="pending"),
            error=case(
                (last_attempt, "worker stopped during the last attempt"), else_=Document.error
            ),
        )
    )
    # AsyncSession.execute is typed as Result, but a DML statement returns a CursorResult.
    return cast(CursorResult[Any], await db.execute(stmt)).rowcount


async def claim_next(db: AsyncSession) -> Document | None:
    next_id = (
        select(Document.id)
        .where(Document.status == "pending", Document.run_after <= func.now())
        .order_by(Document.run_after)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    stmt = (
        update(Document)
        .where(Document.id == next_id)
        .values(status="processing", attempts=Document.attempts + 1)
        .returning(Document)
    )
    return await db.scalar(stmt)


async def _finish(db: AsyncSession, id: UUID, **values: object) -> None:
    stmt = (
        update(Document).where(Document.id == id, Document.status == "processing").values(**values)
    )
    await db.execute(stmt)


async def mark_ready(db: AsyncSession, id: UUID, embed_model: str) -> None:
    await _finish(db, id, status="ready", error=None, embed_model=embed_model)


async def requeue(db: AsyncSession, id: UUID, error: str, delay: timedelta) -> None:
    await _finish(db, id, status="pending", run_after=func.now() + delay, error=error)


async def mark_failed(db: AsyncSession, id: UUID, error: str) -> None:
    await _finish(db, id, status="failed", error=error)


async def try_worker_lock(conn: AsyncConnection) -> bool:
    """Session-level lock: held until released or `conn` closes, so keep `conn` open."""
    return bool(await conn.scalar(select(func.pg_try_advisory_lock(WORKER_LOCK_KEY))))
