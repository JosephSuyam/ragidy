from pydantic import validate_email
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import AppError
from app.models.accounts import User
from app.repositories import owners, sessions, users
from app.services.owners import resolve_guest
from app.services.passwords import hash_password, needs_rehash, verify_password
from app.services.rate_limit import auth_requests, login_failures, rate_limited
from app.services.tokens import hash_token, new_token


async def register(
    db: AsyncSession,
    email: str,
    password: str,
    *,
    ip_key: str,
    session_token: str | None,
    guest_token: str | None,
) -> tuple[User, str]:
    """Create a password user and its session; returns the user and the raw session token."""
    _limit_auth_requests(ip_key)
    email = _normalize(email)
    # Hashed before any query, so no pooled connection idles in a transaction during argon2.
    password_hash = await hash_password(password)
    if await users.get_user_by_email(db, email) is not None:
        raise _email_taken()
    try:
        user = await users.create_user(db, email, password_hash)
    except IntegrityError as exc:  # a concurrent registration won the unique email
        raise _email_taken() from exc
    token = await start_session(db, user, session_token, guest_token)
    await db.commit()
    return user, token


async def login(
    db: AsyncSession,
    email: str,
    password: str,
    *,
    ip_key: str,
    session_token: str | None,
    guest_token: str | None,
) -> tuple[User, str]:
    """Check a password and start a new session; returns the user and the raw session token."""
    _limit_auth_requests(ip_key)
    try:
        email = _normalize(email)
    except ValueError as exc:
        raise _invalid_credentials() from exc
    failures = login_failures()
    failure_key = f"{email}|{ip_key}"
    # Each attempt reserves a failure slot before verifying, so a parallel burst cannot exceed
    # the limit, and a correct password after too many failures still gets 429.
    retry_after = failures.hit(failure_key, get_settings().login_max_failures)
    if retry_after is not None:
        raise rate_limited(retry_after)
    user = await users.get_user_by_email(db, email)
    # Ends the read transaction before argon2 so no pooled connection idles in it;
    # expire_on_commit=False keeps `user` loaded (ADR 0005).
    await db.commit()
    if user is None or user.password is None or not await verify_password(user.password, password):
        raise _invalid_credentials()
    failures.discard(failure_key)
    if needs_rehash(user.password):
        await users.set_password(db, user.id, await hash_password(password))
    token = await start_session(db, user, session_token, guest_token)
    await db.commit()
    return user, token


async def logout(db: AsyncSession, session_token: str | None) -> None:
    if session_token:
        await sessions.delete_session(db, hash_token(session_token))
        await db.commit()


async def start_session(
    db: AsyncSession, user: User, session_token: str | None, guest_token: str | None
) -> str:
    """Replace the incoming session with a new one and migrate the guest; flush only.

    The caller commits once, so a failed migration also undoes the new session.
    Returns the raw token for the cookie.
    """
    if session_token:
        await sessions.delete_session(db, hash_token(session_token))
    token = new_token()
    await sessions.create_session(db, user.id, hash_token(token), get_settings().session_ttl_days)
    await _migrate_guest(db, user, guest_token)
    return token


async def _migrate_guest(db: AsyncSession, user: User, guest_token: str | None) -> None:
    """Move the active guest's documents and chats to `user`, ignoring the user's cap (R6)."""
    guest = await resolve_guest(db, guest_token)
    # The owner row is gone when a purge or another login won the race: nothing to move.
    if guest is None or not await owners.lock_owner(db, guest.owner_id):
        return
    await owners.transfer_owned_rows(db, guest.owner_id, user.owner_id)
    await owners.delete_owner(db, guest.owner_id)


def _limit_auth_requests(ip_key: str) -> None:
    retry_after = auth_requests.hit(ip_key, get_settings().rate_limit_auth_per_minute)
    if retry_after is not None:
        raise rate_limited(retry_after)


def _normalize(email: str) -> str:
    """The stored form of an email; the same EmailStr validation for register and login.

    Raises ValueError when `email` is not a valid address.
    """
    return validate_email(email)[1].lower()


def _invalid_credentials() -> AppError:
    return AppError(401, "invalid_credentials", "Wrong email or password")


def _email_taken() -> AppError:
    return AppError(409, "email_taken", "An account with this email already exists")
