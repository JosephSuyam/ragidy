from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Tier, get_settings
from app.core.errors import AppError
from app.models.accounts import Guest
from app.repositories import guests, owners, sessions
from app.services.rate_limit import guest_creations, rate_limited
from app.services.tokens import hash_token, new_token


@dataclass(frozen=True)
class CurrentOwner:
    owner_id: UUID
    tier: Tier
    email: str | None
    guest_expires_at: datetime | None


def _guest_owner(guest: Guest) -> CurrentOwner:
    return CurrentOwner(guest.owner_id, "guest", None, guest.expires_at)


async def resolve_guest(db: AsyncSession, token: str | None) -> CurrentOwner | None:
    """The active guest of a cookie token; unknown or expired tokens resolve to None."""
    if not token:
        return None
    guest = await guests.get_active_guest(db, hash_token(token))
    return None if guest is None else _guest_owner(guest)


async def resolve_session(db: AsyncSession, token: str | None) -> CurrentOwner | None:
    """The user of an active session token; unknown or expired tokens resolve to None."""
    if not token:
        return None
    user = await sessions.get_session_user(db, hash_token(token))
    return None if user is None else CurrentOwner(user.owner_id, "user", user.email, None)


async def lock_write_owner(db: AsyncSession, owner: CurrentOwner) -> None:
    """Lock the owner row before a write's insert; 401 when a purge or migration deleted it."""
    if not await owners.lock_owner(db, owner.owner_id):
        raise AppError(401, "session_expired", "Your session expired; refresh and try again")


async def create_guest(db: AsyncSession, key: str) -> tuple[CurrentOwner, str]:
    """Create a guest for client IP key `key`, flushing only; the write's service commits.

    Returns the owner and the raw token for the cookie.
    """
    settings = get_settings()
    retry_after = guest_creations.hit(key, settings.guest_create_per_ip_per_hour)
    if retry_after is not None:
        raise rate_limited(retry_after)
    token = new_token()
    guest = await guests.create_guest(db, hash_token(token), settings.guest_ttl_days)
    return _guest_owner(guest), token
