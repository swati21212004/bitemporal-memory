"""
Bitemporal AI Memory System — Pydantic v2 request/response schemas.

Defines all data-transfer objects (DTOs) that flow between the API layer and
the service layer.  Every schema uses Pydantic v2's ``model_config`` and
field validators rather than the legacy ``Config`` inner class.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator


# ── Request Schemas ──────────────────────────────────────────────────────────


class MemoryCreate(BaseModel):
    """Payload for creating a new memory."""

    content: str = Field(
        ...,
        min_length=1,
        description="The textual content of the memory to store.",
    )
    memory_type: Literal["episodic", "semantic", "procedural"] = Field(
        default="semantic",
        description="Category of memory: episodic (events), semantic (facts), or procedural (how-to).",
    )
    importance: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Subjective importance weight (0 = trivial, 1 = critical).",
    )
    tags: list[str] = Field(
        default_factory=list,
        description="Freeform tags for categorical filtering.",
    )
    source: str = Field(
        default="conversation",
        description="Provenance indicator (e.g. 'conversation', 'api', 'import').",
    )
    metadata: dict = Field(
        default_factory=dict,
        description="Arbitrary JSON metadata attached to the memory.",
    )
    valid_from: datetime | None = Field(
        default=None,
        description=(
            "When the fact became true in reality.  "
            "Defaults to *now* if omitted (set server-side)."
        ),
    )


class MemorySearchQuery(BaseModel):
    """Parameters for a semantic + hybrid memory search."""

    query: str = Field(
        ...,
        min_length=1,
        description="Natural-language search query.",
    )
    top_k: int = Field(
        default=10,
        ge=1,
        le=100,
        description="Maximum number of results to return.",
    )
    memory_type: str | None = Field(
        default=None,
        description="Optional filter by memory type.",
    )
    tags: list[str] | None = Field(
        default=None,
        description="Optional filter — returned memories must contain *all* listed tags.",
    )


class TemporalQuery(BaseModel):
    """Query the system's state at a specific point in time."""

    as_of: datetime = Field(
        ...,
        description="The bi-temporal reference timestamp.",
    )
    user_id: str = Field(
        default="default",
        description="Scope the snapshot to a particular user.",
    )


class ForgetRequest(BaseModel):
    """
    Request to soft-delete a memory.

    At least one of ``memory_id`` or ``query`` must be supplied so the system
    can identify the target memory.
    """

    memory_id: uuid.UUID | None = Field(
        default=None,
        description="Exact ID of the memory to forget.",
    )
    query: str | None = Field(
        default=None,
        description="Natural-language query to locate the memory to forget.",
    )
    reason: str | None = Field(
        default=None,
        description="Audit-trail reason for the deletion.",
    )

    @model_validator(mode="after")
    def _require_id_or_query(self) -> ForgetRequest:
        """Ensure the caller provides at least one locator."""
        if self.memory_id is None and self.query is None:
            raise ValueError(
                "At least one of 'memory_id' or 'query' must be provided."
            )
        return self


class ForgetByQueryRequest(BaseModel):
    """Forget all memories matching a semantic query above a threshold."""

    query: str = Field(
        ...,
        min_length=1,
        description="Semantic query used to find memories to forget.",
    )
    threshold: float = Field(
        default=0.8,
        ge=0.0,
        le=1.0,
        description="Minimum similarity score to qualify for deletion.",
    )
    reason: str | None = Field(
        default=None,
        description="Audit-trail reason for the bulk deletion.",
    )


class ContradictionResolution(BaseModel):
    """User's decision on how to resolve a detected contradiction."""

    keep: Literal["existing", "new", "both"] = Field(
        ...,
        description=(
            "'existing' = discard the new content, "
            "'new' = supersede the old memory, "
            "'both' = store both and link them."
        ),
    )
    reason: str | None = Field(
        default=None,
        description="Optional explanation for the resolution choice.",
    )


# ── Response Schemas ─────────────────────────────────────────────────────────


class MemoryResponse(BaseModel):
    """
    Full read-representation of a stored memory.

    Uses ``from_attributes = True`` so it can be constructed directly from
    SQLAlchemy model instances.
    """

    model_config = {"from_attributes": True}

    id: uuid.UUID
    user_id: str
    content: str
    memory_type: str
    tags: list[str]
    source: str
    metadata: dict = Field(validation_alias="metadata_")
    importance: float
    access_count: int
    last_accessed_at: datetime
    decay_score: float
    created_at: datetime
    superseded_at: datetime | None
    valid_from: datetime
    valid_to: datetime | None
    is_deleted: bool
    deleted_at: datetime | None
    supersedes_id: uuid.UUID | None
    contradiction_of: uuid.UUID | None


class ContradictionResponse(BaseModel):
    """
    Returned when a new memory contradicts an existing one.

    The client should inspect ``similarity_score`` and ``message``, then call
    the contradiction-resolution endpoint with a
    :class:`ContradictionResolution`.
    """

    existing_memory: MemoryResponse
    new_content: str
    similarity_score: float
    message: str


class SystemPromptContext(BaseModel):
    """
    Pre-formatted memory context block destined for an LLM system prompt.
    """

    memories: list[MemoryResponse]
    generated_at: datetime
    stale_count: int = Field(
        default=0,
        description="Number of active memories whose decay score is below the staleness threshold.",
    )
