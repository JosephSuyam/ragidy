from datetime import timedelta
from uuid import UUID

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import Session, User


async def create_session(db: AsyncSession, user_id: UUID, token_hash: bytes, ttl_days: int) -> None:
    # now() is the transaction start, so expires_at - created_at is exactly the TTL.
    await db.execute(
        insert(Session).values(
            user_id=user_id,
            token=token_hash,
            expires_at=func.now() + timedelta(days=ttl_days),
        )
    )


async def get_session_user(db: AsyncSession, token_hash: bytes) -> User | None:
    stmt = (
        select(User)
        .join(Session, Session.user_id == User.id)
        .where(Session.token == token_hash, Session.expires_at > func.now())
    )
    return await db.scalar(stmt)


async def delete_session(db: AsyncSession, token_hash: bytes) -> None:
    await db.execute(delete(Session).where(Session.token == token_hash))
