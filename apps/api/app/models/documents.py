import uuid
from datetime import datetime
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, CreatedAt, UuidPk


class Document(Base):
    """One upload or URL, and its ingestion job (ADR 0002). Its object key is documents/<id>."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'processing', 'ready', 'failed')", name="status"),
        CheckConstraint(
            "status <> 'failed' OR (error IS NOT NULL AND error <> '')", name="failed_has_error"
        ),
        Index(
            "ix_documents_pending_run_after",
            "run_after",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    id: Mapped[UuidPk]
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("owners.id", ondelete="RESTRICT"), index=True
    )
    source: Mapped[str]
    status: Mapped[str] = mapped_column(server_default="pending")
    error: Mapped[str | None]
    embed_model: Mapped[str]
    attempts: Mapped[int] = mapped_column(server_default="0")
    run_after: Mapped[datetime] = mapped_column(server_default=func.now())
    created_at: Mapped[CreatedAt]


class Chunk(Base):
    """One embedded chunk of a document. The vector has no fixed dimension, so models can differ.

    shortcut: exact cosine scan, fine for <=20 docs per owner; add a partial expression HNSW
    index per model dimension when caps grow.
    """

    __tablename__ = "chunks"
    # Also the index for filtering chunks by document.
    __table_args__ = (UniqueConstraint("document_id", "position"),)

    id: Mapped[UuidPk]
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("documents.id", ondelete="CASCADE"))
    position: Mapped[int]
    # `metadata` is reserved on declarative models.
    metadata_: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, server_default=text("'{}'::jsonb")
    )
    text: Mapped[str]
    embedding: Mapped[list[float]] = mapped_column(Vector())


class Chat(Base):
    """A chat's history is its `messages` rows (ADR 0008)."""

    __tablename__ = "chats"
    __table_args__ = (Index("ix_chats_owner_id_created_at", "owner_id", "created_at"),)

    id: Mapped[UuidPk]
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("owners.id", ondelete="RESTRICT"))
    title: Mapped[str | None]
    created_at: Mapped[CreatedAt]


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        CheckConstraint("role IN ('user', 'assistant')", name="role"),
        Index("ix_messages_chat_id_created_at", "chat_id", "created_at"),
    )

    id: Mapped[UuidPk]
    chat_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("chats.id", ondelete="CASCADE"))
    role: Mapped[str]
    content: Mapped[str]
    citations: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    created_at: Mapped[CreatedAt]
