"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-11-05 10:36:36.247660
"""

import uuid
from collections.abc import Sequence
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id() -> sa.Column[uuid.UUID]:
    return sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False)


def _created_at() -> sa.Column[datetime]:
    return sa.Column(
        "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
    )


def upgrade() -> None:
    op.create_table(
        "owners",
        _id(),
        sa.Column("kind", sa.Text(), nullable=False),
        _created_at(),
        sa.CheckConstraint("kind IN ('user', 'guest')", name=op.f("ck_owners_kind")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_owners")),
    )
    op.create_table(
        "users",
        _id(),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.Text(), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("password", sa.Text(), nullable=True),
        _created_at(),
        sa.CheckConstraint("email = lower(btrim(email))", name=op.f("ck_users_email_normalized")),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["owners.id"], name=op.f("fk_users_owner_id_owners"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        sa.UniqueConstraint("owner_id", name=op.f("uq_users_owner_id")),
    )
    op.create_table(
        "guests",
        _id(),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["owners.id"], name=op.f("fk_guests_owner_id_owners"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_guests")),
        sa.UniqueConstraint("owner_id", name=op.f("uq_guests_owner_id")),
        sa.UniqueConstraint("token", name=op.f("uq_guests_token")),
    )
    op.create_index(op.f("ix_guests_expires_at"), "guests", ["expires_at"])
    op.create_table(
        "sessions",
        _id(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_sessions_user_id_users"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token", name=op.f("uq_sessions_token")),
    )
    op.create_index(op.f("ix_sessions_expires_at"), "sessions", ["expires_at"])
    op.create_index(op.f("ix_sessions_user_id"), "sessions", ["user_id"])
    op.create_table(
        "oauth_accounts",
        _id(),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("provider_user_id", sa.Text(), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_oauth_accounts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_oauth_accounts")),
        sa.UniqueConstraint(
            "provider",
            "provider_user_id",
            name=op.f("uq_oauth_accounts_provider_provider_user_id"),
        ),
    )
    op.create_index(op.f("ix_oauth_accounts_user_id"), "oauth_accounts", ["user_id"])
    op.create_table(
        "documents",
        _id(),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), server_default="pending", nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("embed_model", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "run_after", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        _created_at(),
        sa.CheckConstraint(
            "status <> 'failed' OR (error IS NOT NULL AND error <> '')",
            name=op.f("ck_documents_failed_has_error"),
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed')",
            name=op.f("ck_documents_status"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_id"],
            ["owners.id"],
            name=op.f("fk_documents_owner_id_owners"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_documents")),
    )
    op.create_index(op.f("ix_documents_owner_id"), "documents", ["owner_id"])
    op.create_index(
        "ix_documents_pending_run_after",
        "documents",
        ["run_after"],
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_table(
        "chats",
        _id(),
        sa.Column("owner_id", sa.Uuid(), nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["owner_id"], ["owners.id"], name=op.f("fk_chats_owner_id_owners"), ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_chats")),
    )
    op.create_index("ix_chats_owner_id_created_at", "chats", ["owner_id", "created_at"])


def downgrade() -> None:
    # Dropping a table drops its indexes and constraints; children go before parents.
    for table in ("chats", "documents", "oauth_accounts", "sessions", "guests", "users", "owners"):
        op.drop_table(table)
