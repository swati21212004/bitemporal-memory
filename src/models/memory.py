"""
Bitemporal AI Memory System — SQLAlchemy ORM models.

Maps the `memories` and `memory_audit_log` tables to Python classes
using SQLAlchemy 2.0 declarative style with pgvector support.
"""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all ORM models."""
    pass


class Memory(Base):
    """
    Core memory entity with bitemporal tracking.

    System time: created_at / superseded_at — when the DB recorded the fact.
    Valid time:  valid_from / valid_to       — when the fact was true in reality.

    Soft-delete only. Never hard delete.
    """

    __tablename__ = "memories"

    # ── Identity ──────────────────────────────────────────────────────────
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="default",
    )

    # ── Content ───────────────────────────────────────────────────────────
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding = mapped_column(Vector(1536), nullable=False)
    memory_type: Mapped[str] = mapped_column(
        Enum("episodic", "semantic", "procedural", name="memory_type"),
        nullable=False,
        default="semantic",
    )
    tags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
    )
    source: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="conversation",
    )
    metadata_: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
    )

    # ── Importance & Decay ────────────────────────────────────────────────
    importance: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
    )
    access_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    last_accessed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    decay_score: Mapped[float] = mapped_column(
        Float,
        nullable=False,
        default=0.5,
    )

    # ── Bitemporal: System Time ───────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # ── Bitemporal: Valid Time ────────────────────────────────────────────
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )
    valid_to: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # ── Soft Delete ───────────────────────────────────────────────────────
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        default=None,
    )

    # ── Lineage ───────────────────────────────────────────────────────────
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memories.id"),
        nullable=True,
        default=None,
    )
    contradiction_of: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memories.id"),
        nullable=True,
        default=None,
    )

    # ── Relationships ─────────────────────────────────────────────────────
    audit_entries: Mapped[list["MemoryAuditLog"]] = relationship(
        back_populates="memory",
        lazy="selectin",
    )

    # ── Table constraints ─────────────────────────────────────────────────
    __table_args__ = (
        CheckConstraint(
            "importance >= 0.0 AND importance <= 1.0",
            name="ck_importance_bounds",
        ),
        Index(
            "idx_memories_decay_score",
            decay_score.desc(),
            postgresql_where=text("is_deleted = false AND superseded_at IS NULL"),
        ),
        Index(
            "idx_memories_active",
            "user_id",
            "memory_type",
            decay_score.desc(),
            postgresql_where=text(
                "is_deleted = false AND superseded_at IS NULL AND valid_to IS NULL"
            ),
        ),
        Index("idx_memories_user_id", "user_id", postgresql_where=text("is_deleted = false")),
    )

    def __repr__(self) -> str:
        return (
            f"<Memory(id={self.id!s:.8}, type={self.memory_type}, "
            f"importance={self.importance}, decay={self.decay_score:.3f})>"
        )


class MemoryAuditLog(Base):
    """
    Immutable audit trail for all memory operations.

    Every create, supersede, and forget operation is logged here.
    """

    __tablename__ = "memory_audit_log"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    memory_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("memories.id"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="default",
    )
    action: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    old_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    performed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("now()"),
    )

    # ── Relationships ─────────────────────────────────────────────────────
    memory: Mapped["Memory"] = relationship(back_populates="audit_entries")

    def __repr__(self) -> str:
        return f"<AuditLog(memory={self.memory_id!s:.8}, action={self.action})>"
