from datetime import timedelta

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import Guest, Owner


async def create_guest(db: AsyncSession, token_hash: bytes, ttl_days: int) -> Guest:
    """Insert an owner and its guest; flush only, the caller commits."""
    owner_id = (
        await db.execute(insert(Owner).values(kind="guest").returning(Owner.id))
    ).scalar_one()
    # now() is the transaction start, so expires_at - created_at is exactly the TTL.
    stmt = (
        insert(Guest)
        .values(
            owner_id=owner_id,
            token=token_hash,
            expires_at=func.now() + timedelta(days=ttl_days),
        )
        .returning(Guest)
    )
    guest = (await db.scalars(stmt)).one()
    return guest


async def get_active_guest(db: AsyncSession, token_hash: bytes) -> Guest | None:
    stmt = select(Guest).where(Guest.token == token_hash, Guest.expires_at > func.now())
    return await db.scalar(stmt)
