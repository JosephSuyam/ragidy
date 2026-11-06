from uuid import UUID

from sqlalchemy import insert, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.accounts import OAuthAccount, Owner, User


async def get_user_by_email(db: AsyncSession, email: str) -> User | None:
    return await db.scalar(select(User).where(User.email == email))


async def get_user_by_identity(
    db: AsyncSession, provider: str, provider_user_id: str
) -> User | None:
    stmt = (
        select(User)
        .join(OAuthAccount, OAuthAccount.user_id == User.id)
        .where(
            OAuthAccount.provider == provider,
            OAuthAccount.provider_user_id == provider_user_id,
        )
    )
    return await db.scalar(stmt)


async def create_user(db: AsyncSession, email: str | None, password_hash: str | None) -> User:
    """Insert an owner and its user; flush only, the caller commits.

    A duplicate email raises IntegrityError.
    """
    owner_id = (
        await db.execute(insert(Owner).values(kind="user").returning(Owner.id))
    ).scalar_one()
    stmt = (
        insert(User).values(owner_id=owner_id, email=email, password=password_hash).returning(User)
    )
    return (await db.scalars(stmt)).one()


async def set_password(db: AsyncSession, user_id: UUID, password_hash: str | None) -> None:
    await db.execute(update(User).where(User.id == user_id).values(password=password_hash))


async def add_identity(
    db: AsyncSession, user_id: UUID, provider: str, provider_user_id: str
) -> None:
    """A duplicate (provider, provider_user_id) raises IntegrityError."""
    await db.execute(
        insert(OAuthAccount).values(
            user_id=user_id, provider=provider, provider_user_id=provider_user_id
        )
    )
