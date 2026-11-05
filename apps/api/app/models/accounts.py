import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPk


class Owner(Base):
    """The one owner of documents and chats: either a user or a guest (ADR 0003)."""

    __tablename__ = "owners"
    __table_args__ = (CheckConstraint("kind IN ('user', 'guest')", name="kind"),)

    id: Mapped[UuidPk]
    kind: Mapped[str]
    created_at: Mapped[CreatedAt]


class User(Base):
    __tablename__ = "users"
    __table_args__ = (
        # Stored normalized, so the unique constraint on email is unique on the normalized form.
        CheckConstraint("email = lower(btrim(email))", name="email_normalized"),
    )

    id: Mapped[UuidPk]
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), unique=True
    )
    email: Mapped[str | None] = mapped_column(unique=True)
    name: Mapped[str | None]
    password: Mapped[str | None]  # hash only, never the plaintext password
    created_at: Mapped[CreatedAt]


class Guest(Base):
    __tablename__ = "guests"

    id: Mapped[UuidPk]
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="CASCADE"), unique=True
    )
    # hash of the cookie token, never the raw token
    token: Mapped[bytes] = mapped_column(unique=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[CreatedAt]


class Session(Base):
    __tablename__ = "sessions"

    id: Mapped[UuidPk]
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # hash of the cookie token, never the raw token
    token: Mapped[bytes] = mapped_column(unique=True)
    expires_at: Mapped[datetime] = mapped_column(index=True)
    created_at: Mapped[CreatedAt]


class OAuthAccount(Base):
    __tablename__ = "oauth_accounts"
    __table_args__ = (UniqueConstraint("provider", "provider_user_id"),)

    id: Mapped[UuidPk]
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[str]
    provider_user_id: Mapped[str]
    created_at: Mapped[CreatedAt]
