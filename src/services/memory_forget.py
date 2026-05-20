"""
Bitemporal AI Memory System — Forget-path service.

Implements soft-delete operations for memories. NEVER performs hard deletes.
All forget operations set ``is_deleted=True`` and record an immutable audit log
entry so the action is traceable and recoverable.

Three forget strategies are provided:
  1. **By ID** — forget a single memory by its UUID.
  2. **By semantic query** — embed a query, find similar memories, and
     optionally soft-delete them after user confirmation.
  3. **By time range** — forget all memories whose ``valid_from`` falls
     within a given time window.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.memory import Memory, MemoryAuditLog
from src.schemas.memory import ForgetByQueryRequest, ForgetRequest, MemoryResponse
from src.services.embedding import get_embedding_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    """Return the current UTC timestamp (timezone-aware)."""
    return datetime.now(timezone.utc)


def _to_response(memory: Memory) -> MemoryResponse:
    """Convert a Memory ORM instance to a MemoryResponse schema."""
    return MemoryResponse.model_validate(memory, from_attributes=True)


async def _soft_delete_memory(
    session: AsyncSession,
    memory: Memory,
    user_id: str,
    reason: str | None = None,
) -> Memory:
    """Apply soft-delete to a single Memory and create an audit log entry.

    Parameters
    ----------
    session:
        The active async database session (caller manages the transaction).
    memory:
        The ORM memory instance to soft-delete.
    user_id:
        The user performing the action (for the audit trail).
    reason:
        Optional human-readable reason for the deletion.

    Returns
    -------
    Memory
        The updated Memory instance with ``is_deleted=True``.
    """
    now = _now_utc()

    memory.is_deleted = True
    memory.deleted_at = now
    memory.valid_to = now

    audit = MemoryAuditLog(
        memory_id=memory.id,
        user_id=user_id,
        action="forget",
        reason=reason,
        old_content=memory.content,
        new_content=None,
    )
    session.add(audit)
    await session.flush()

    logger.info("Soft-deleted memory %s for user %s (reason=%s)", memory.id, user_id, reason)
    return memory


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def forget_by_id(
    session: AsyncSession,
    memory_id: UUID,
    user_id: str = "default",
    reason: str | None = None,
) -> MemoryResponse:
    """Soft-delete a single memory by its primary-key UUID.

    Parameters
    ----------
    session:
        Async SQLAlchemy session.
    memory_id:
        Primary key of the memory to forget.
    user_id:
        Owner of the memory — used to prevent cross-user deletion.
    reason:
        Optional reason recorded in the audit log.

    Returns
    -------
    MemoryResponse
        The updated (soft-deleted) memory.

    Raises
    ------
    ValueError
        If the memory does not exist, does not belong to the user, or is
        already deleted.
    """
    stmt = select(Memory).where(Memory.id == memory_id)
    result = await session.execute(stmt)
    memory = result.scalar_one_or_none()

    if memory is None:
        raise ValueError(f"Memory {memory_id} not found")
    if memory.user_id != user_id:
        raise ValueError(f"Memory {memory_id} does not belong to user {user_id}")
    if memory.is_deleted:
        raise ValueError(f"Memory {memory_id} is already deleted")

    memory = await _soft_delete_memory(session, memory, user_id, reason)
    return _to_response(memory)


async def forget_by_query(
    session: AsyncSession,
    query: str,
    user_id: str = "default",
    threshold: float = 0.8,
    reason: str | None = None,
    confirm: bool = False,
) -> dict:
    """Find memories semantically similar to *query* and optionally forget them.

    This is a **two-phase** operation:

    1. **Preview** (``confirm=False``): returns the matching memories so the
       caller can review them before committing.
    2. **Execute** (``confirm=True``): soft-deletes all matching memories and
       returns the deleted list.

    Parameters
    ----------
    session:
        Async SQLAlchemy session.
    query:
        Natural-language query whose embedding is compared to stored memories.
    user_id:
        Only memories belonging to this user are considered.
    threshold:
        Minimum cosine similarity for a memory to be considered a match.
        Defaults to ``0.8``.
    reason:
        Optional reason recorded in each audit log entry.
    confirm:
        If ``False`` (default), return matches without deleting.
        If ``True``, soft-delete every match.

    Returns
    -------
    dict
        * Preview mode: ``{'matches': list[MemoryResponse], 'count': int, 'message': str}``
        * Confirm mode: ``{'deleted': list[MemoryResponse], 'count': int}``
    """
    # 1. Embed the query string.
    embedding_service = get_embedding_service()
    query_embedding = await embedding_service.embed(query)
    embedding_literal = "[" + ",".join(str(v) for v in query_embedding) + "]"

    # 2. Find matching memories (cosine similarity > threshold).
    #    pgvector cosine *distance* = 1 - cosine_similarity, so we filter
    #    where distance < (1 - threshold).
    from sqlalchemy import text as sa_text

    similarity_sql = sa_text(
        """
        SELECT id
        FROM memories
        WHERE user_id = :user_id
          AND is_deleted = false
          AND superseded_at IS NULL
          AND (1 - (embedding <=> :embedding::vector)) > :threshold
        ORDER BY embedding <=> :embedding::vector
        """
    )
    result = await session.execute(
        similarity_sql,
        {
            "user_id": user_id,
            "embedding": embedding_literal,
            "threshold": threshold,
        },
    )
    matching_ids = [row[0] for row in result.fetchall()]

    if not matching_ids:
        return {
            "matches" if not confirm else "deleted": [],
            "count": 0,
            "message": "No memories matched the query at the given threshold.",
        }

    # 3. Load full ORM objects.
    stmt = select(Memory).where(Memory.id.in_(matching_ids))
    orm_result = await session.execute(stmt)
    memories = list(orm_result.scalars().all())

    # 4a. Preview mode — return matches without modifying anything.
    if not confirm:
        return {
            "matches": [_to_response(m) for m in memories],
            "count": len(memories),
            "message": "Review matches and confirm deletion",
        }

    # 4b. Execute mode — soft-delete all matches.
    deleted: list[MemoryResponse] = []
    for mem in memories:
        mem = await _soft_delete_memory(session, mem, user_id, reason)
        deleted.append(_to_response(mem))

    logger.info(
        "Forgot %d memories for user %s via query (threshold=%.2f)",
        len(deleted),
        user_id,
        threshold,
    )
    return {"deleted": deleted, "count": len(deleted)}


async def forget_by_time_range(
    session: AsyncSession,
    user_id: str,
    start: datetime,
    end: datetime,
    reason: str | None = None,
) -> dict:
    """Soft-delete all active memories whose ``valid_from`` is within [start, end].

    Parameters
    ----------
    session:
        Async SQLAlchemy session.
    user_id:
        Only memories belonging to this user are affected.
    start:
        Inclusive lower bound of the valid-from time range.
    end:
        Inclusive upper bound of the valid-from time range.
    reason:
        Optional reason recorded in each audit log entry.

    Returns
    -------
    dict
        ``{'deleted_count': int}``
    """
    stmt = select(Memory).where(
        Memory.user_id == user_id,
        Memory.is_deleted == False,  # noqa: E712 — SQLAlchemy requires ==
        Memory.valid_from >= start,
        Memory.valid_from <= end,
    )
    result = await session.execute(stmt)
    memories = list(result.scalars().all())

    for mem in memories:
        await _soft_delete_memory(session, mem, user_id, reason)

    logger.info(
        "Forgot %d memories for user %s in range [%s, %s]",
        len(memories),
        user_id,
        start.isoformat(),
        end.isoformat(),
    )
    return {"deleted_count": len(memories)}
