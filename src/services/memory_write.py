"""
Bitemporal AI Memory System — Write-path service.

Handles all memory mutations: creation, deduplication, contradiction
detection, and contradiction resolution.  Every mutation is recorded in the
immutable :class:`MemoryAuditLog`.

Usage::

    from src.services.memory_write import write_memory, resolve_contradiction

    result = await write_memory(session, MemoryCreate(content="..."))
    if isinstance(result, ContradictionResponse):
        # Present contradiction to user, then resolve
        resolved = await resolve_contradiction(
            session, result.existing_memory.id, resolution, data, user_id
        )
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.memory import Memory, MemoryAuditLog
from src.schemas.memory import (
    ContradictionResolution,
    ContradictionResponse,
    MemoryCreate,
    MemoryResponse,
)
from src.services.embedding import get_embedding_service

logger = logging.getLogger(__name__)


# ── Public API ───────────────────────────────────────────────────────────────


async def write_memory(
    session: AsyncSession,
    data: MemoryCreate,
    user_id: str = "default",
) -> MemoryResponse | ContradictionResponse:
    """
    Create a new memory, guarding against duplicates and contradictions.

    Pipeline
    --------
    1. Embed ``data.content`` via the embedding service.
    2. Retrieve the top-5 most similar *active* memories for the user.
    3. If any existing memory exceeds the **deduplication** threshold
       (default 0.95), raise ``ValueError``.
    4. If any existing memory exceeds the **contradiction** threshold
       (default 0.85), return a :class:`ContradictionResponse` so the
       caller can ask the user how to proceed.
    5. Otherwise, persist the new :class:`Memory` row and a ``create``
       audit-log entry, then return a :class:`MemoryResponse`.

    Parameters
    ----------
    session : AsyncSession
        Active SQLAlchemy async session (caller manages the transaction).
    data : MemoryCreate
        Validated creation payload.
    user_id : str
        Owner of the memory.

    Returns
    -------
    MemoryResponse | ContradictionResponse
        The created memory, *or* a contradiction requiring resolution.

    Raises
    ------
    ValueError
        If a near-duplicate memory already exists.
    """
    embedding_service = get_embedding_service()
    embedding = await embedding_service.embed(data.content)

    # ── Step 2: Duplicate / contradiction check ──────────────────────────
    contradiction = await _check_duplicates_and_contradictions(
        session, embedding, user_id, data.content
    )
    if contradiction is not None:
        return contradiction

    # ── Step 4-7: Persist ────────────────────────────────────────────────
    memory = _build_memory(data, embedding, user_id)
    session.add(memory)
    await session.flush()  # populates memory.id and server defaults

    audit = MemoryAuditLog(
        memory_id=memory.id,
        user_id=user_id,
        action="create",
        new_content=data.content,
    )
    session.add(audit)
    await session.flush()

    logger.info("Created memory %s for user=%s", memory.id, user_id)
    return MemoryResponse.model_validate(memory)


async def resolve_contradiction(
    session: AsyncSession,
    existing_id: uuid.UUID,
    resolution: ContradictionResolution,
    new_data: MemoryCreate,
    user_id: str = "default",
) -> MemoryResponse:
    """
    Apply the user's decision for a detected contradiction.

    Strategies
    ----------
    * **``keep='new'``** — Supersede the existing memory (set
      ``superseded_at``) and create a replacement that carries a
      ``supersedes_id`` link back to the old version.
    * **``keep='existing'``** — Discard the new content; only log the
      decision.  Returns the existing memory unchanged.
    * **``keep='both'``** — Store both side-by-side; the new memory is
      linked via ``contradiction_of``.

    Parameters
    ----------
    session : AsyncSession
        Active async session.
    existing_id : UUID
        ID of the conflicting existing memory.
    resolution : ContradictionResolution
        The user's chosen strategy.
    new_data : MemoryCreate
        Original creation payload for the new memory.
    user_id : str
        Owner of the memory.

    Returns
    -------
    MemoryResponse
        The surviving or newly created memory.
    """
    existing = await session.get(Memory, existing_id)
    if existing is None:
        raise ValueError(f"Existing memory {existing_id} not found.")

    now = datetime.now(timezone.utc)

    if resolution.keep == "new":
        return await _resolve_keep_new(
            session, existing, new_data, user_id, now, resolution.reason
        )
    elif resolution.keep == "existing":
        return await _resolve_keep_existing(
            session, existing, new_data, user_id, resolution.reason
        )
    else:  # "both"
        return await _resolve_keep_both(
            session, existing, new_data, user_id, resolution.reason
        )


# ── Private helpers ──────────────────────────────────────────────────────────


async def _check_duplicates_and_contradictions(
    session: AsyncSession,
    embedding: list[float],
    user_id: str,
    new_content: str,
) -> ContradictionResponse | None:
    """
    Query the top-5 similar active memories and enforce guardrails.

    Returns
    -------
    ContradictionResponse | None
        ``None`` when the content is safe to insert; otherwise a
        :class:`ContradictionResponse` for the most-similar conflicting
        memory.

    Raises
    ------
    ValueError
        If the content is a near-exact duplicate.
    """
    result = await session.execute(
        sa_text(
            """
            SELECT id, content, 1 - (embedding <=> :query_embedding) AS similarity
            FROM memories
            WHERE user_id = :user_id
              AND is_deleted = false
              AND superseded_at IS NULL
              AND valid_to IS NULL
            ORDER BY embedding <=> :query_embedding
            LIMIT 5
            """
        ),
        {"query_embedding": str(embedding), "user_id": user_id},
    )
    rows = result.fetchall()

    for row in rows:
        similarity: float = float(row.similarity)

        if similarity >= settings.deduplication_threshold:
            logger.warning(
                "Duplicate detected (sim=%.4f) for existing memory %s",
                similarity,
                row.id,
            )
            raise ValueError(
                f"Duplicate memory detected (similarity={similarity:.4f} "
                f"with memory {row.id})."
            )

        if similarity >= settings.contradiction_threshold:
            logger.info(
                "Contradiction detected (sim=%.4f) with memory %s",
                similarity,
                row.id,
            )
            existing_memory = await session.get(Memory, row.id)
            return ContradictionResponse(
                existing_memory=MemoryResponse.model_validate(existing_memory),
                new_content=new_content,
                similarity_score=similarity,
                message=(
                    f"The new content has a similarity of {similarity:.4f} "
                    f"with an existing memory. Please resolve the "
                    f"contradiction by choosing 'existing', 'new', or 'both'."
                ),
            )

    return None


def _build_memory(
    data: MemoryCreate,
    embedding: list[float],
    user_id: str,
    *,
    supersedes_id: uuid.UUID | None = None,
    contradiction_of: uuid.UUID | None = None,
) -> Memory:
    """Construct a :class:`Memory` instance from validated input."""
    return Memory(
        user_id=user_id,
        content=data.content,
        embedding=embedding,
        memory_type=data.memory_type,
        tags=data.tags,
        source=data.source,
        metadata_=data.metadata,
        importance=data.importance,
        decay_score=data.importance,  # initial decay = importance
        valid_from=data.valid_from or datetime.now(timezone.utc),
        supersedes_id=supersedes_id,
        contradiction_of=contradiction_of,
    )


async def _resolve_keep_new(
    session: AsyncSession,
    existing: Memory,
    new_data: MemoryCreate,
    user_id: str,
    now: datetime,
    reason: str | None,
) -> MemoryResponse:
    """Supersede the old memory and create a replacement."""
    # Mark old memory as superseded
    existing.superseded_at = now
    session.add(existing)

    # Audit: supersede old
    session.add(
        MemoryAuditLog(
            memory_id=existing.id,
            user_id=user_id,
            action="supersede",
            reason=reason,
            old_content=existing.content,
            new_content=new_data.content,
        )
    )

    # Create replacement
    embedding_service = get_embedding_service()
    embedding = await embedding_service.embed(new_data.content)

    new_memory = _build_memory(
        new_data, embedding, user_id, supersedes_id=existing.id
    )
    session.add(new_memory)
    await session.flush()

    # Audit: create new
    session.add(
        MemoryAuditLog(
            memory_id=new_memory.id,
            user_id=user_id,
            action="create",
            reason=f"Supersedes {existing.id} — {reason or 'contradiction resolved'}",
            new_content=new_data.content,
        )
    )
    await session.flush()

    logger.info(
        "Superseded memory %s → %s (keep=new)", existing.id, new_memory.id
    )
    return MemoryResponse.model_validate(new_memory)


async def _resolve_keep_existing(
    session: AsyncSession,
    existing: Memory,
    new_data: MemoryCreate,
    user_id: str,
    reason: str | None,
) -> MemoryResponse:
    """Keep the existing memory; only log the decision."""
    session.add(
        MemoryAuditLog(
            memory_id=existing.id,
            user_id=user_id,
            action="contradiction_resolved",
            reason=reason or "Kept existing memory; discarded new content.",
            old_content=existing.content,
            new_content=new_data.content,
        )
    )
    await session.flush()

    logger.info("Kept existing memory %s (keep=existing)", existing.id)
    return MemoryResponse.model_validate(existing)


async def _resolve_keep_both(
    session: AsyncSession,
    existing: Memory,
    new_data: MemoryCreate,
    user_id: str,
    reason: str | None,
) -> MemoryResponse:
    """Store both memories, linking the new one as a known contradiction."""
    embedding_service = get_embedding_service()
    embedding = await embedding_service.embed(new_data.content)

    new_memory = _build_memory(
        new_data, embedding, user_id, contradiction_of=existing.id
    )
    session.add(new_memory)
    await session.flush()

    session.add(
        MemoryAuditLog(
            memory_id=new_memory.id,
            user_id=user_id,
            action="create",
            reason=(
                f"Stored alongside contradicting memory {existing.id} — "
                f"{reason or 'both kept'}"
            ),
            new_content=new_data.content,
        )
    )
    await session.flush()

    logger.info(
        "Stored both memories: existing=%s, new=%s (keep=both)",
        existing.id,
        new_memory.id,
    )
    return MemoryResponse.model_validate(new_memory)
