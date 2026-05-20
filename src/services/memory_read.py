"""
Bitemporal AI Memory System — Read-path service (the heart of retrieval).

Provides hybrid semantic + decay search, single-memory lookup, version-chain
history, bitemporal snapshots, and LLM system-prompt generation.

All SQL is executed via ``sqlalchemy.text()`` for pgvector operator access.

Usage::

    from src.services.memory_read import search_memories, get_system_prompt_context

    results = await search_memories(session, "What does the user prefer?")
    prompt  = await get_system_prompt_context(session, user_id="alice")
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import text as sa_text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.models.memory import Memory
from src.schemas.memory import MemoryResponse
from src.services.embedding import get_embedding_service

logger = logging.getLogger(__name__)


# ── Hybrid Search ────────────────────────────────────────────────────────────


async def search_memories(
    session: AsyncSession,
    query: str,
    user_id: str = "default",
    top_k: int = 10,
    memory_type: str | None = None,
    tags: list[str] | None = None,
) -> list[MemoryResponse]:
    """
    Retrieve memories ranked by a hybrid relevance score.

    The score blends **semantic similarity** (cosine distance via pgvector)
    with the per-memory **decay score**, weighted by
    :pydata:`settings.semantic_weight` and :pydata:`settings.decay_weight`.

    Pipeline
    --------
    1. Embed the *query* text.
    2. Execute a two-stage SQL query:
       a. **Candidate selection** — top-50 by raw cosine similarity,
          optionally filtered by ``memory_type`` and ``tags``.
       b. **Re-ranking** — blend semantic + decay scores and take *top_k*.
    3. Bump ``access_count`` and ``last_accessed_at`` for every returned row
       (side-effect for decay recalculation).

    Parameters
    ----------
    session : AsyncSession
        Active async session.
    query : str
        Natural-language search query.
    user_id : str
        Scope the search to a particular user.
    top_k : int
        Maximum results to return (1–100).
    memory_type : str | None
        Optional filter (``'episodic'``, ``'semantic'``, ``'procedural'``).
    tags : list[str] | None
        If provided, only memories containing **all** listed tags are returned
        (Postgres ``@>`` array containment operator).

    Returns
    -------
    list[MemoryResponse]
        Memories ordered by descending hybrid relevance score.
    """
    embedding_service = get_embedding_service()
    embedding = await embedding_service.embed(query)

    # ── Build dynamic SQL ────────────────────────────────────────────────
    where_clauses = [
        "m.is_deleted = false",
        "m.superseded_at IS NULL",
        "m.valid_to IS NULL",
        "m.user_id = :user_id",
    ]
    params: dict = {
        "query_vec": str(embedding),
        "user_id": user_id,
        "sem_weight": settings.semantic_weight,
        "dec_weight": settings.decay_weight,
        "top_k": top_k,
    }

    if memory_type is not None:
        where_clauses.append("m.memory_type = :memory_type")
        params["memory_type"] = memory_type

    if tags:
        where_clauses.append("m.tags @> :tags")
        params["tags"] = tags

    where_sql = " AND ".join(where_clauses)

    sql = f"""
        WITH candidates AS (
            SELECT m.*,
                   1 - (m.embedding <=> :query_vec) AS semantic_score
            FROM memories m
            WHERE {where_sql}
            ORDER BY m.embedding <=> :query_vec
            LIMIT 50
        )
        SELECT *,
               (:sem_weight * semantic_score) + (:dec_weight * decay_score)
                   AS relevance_score
        FROM candidates
        ORDER BY relevance_score DESC
        LIMIT :top_k
    """

    result = await session.execute(sa_text(sql), params)
    rows = result.fetchall()

    if not rows:
        return []

    # ── Side-effect: bump access stats ───────────────────────────────────
    returned_ids = [row.id for row in rows]
    await _bump_access(session, returned_ids)

    # ── Map to response schemas ──────────────────────────────────────────
    return [_row_to_response(row) for row in rows]


# ── Single-memory lookup ────────────────────────────────────────────────────


async def get_memory_by_id(
    session: AsyncSession,
    memory_id: uuid.UUID,
) -> MemoryResponse | None:
    """
    Fetch a single memory by primary key.

    Parameters
    ----------
    session : AsyncSession
        Active async session.
    memory_id : UUID
        The memory's primary key.

    Returns
    -------
    MemoryResponse | None
        The memory if found, otherwise ``None``.
    """
    memory = await session.get(Memory, memory_id)
    if memory is None:
        return None
    return MemoryResponse.model_validate(memory)


# ── Version-chain history ───────────────────────────────────────────────────


async def get_memory_history(
    session: AsyncSession,
    memory_id: uuid.UUID,
) -> list[MemoryResponse]:
    """
    Return the full version chain for a memory.

    Uses a recursive CTE that walks the ``supersedes_id`` lineage in both
    directions — ancestors (what this memory superseded) and descendants
    (what superseded this memory).

    Parameters
    ----------
    session : AsyncSession
        Active async session.
    memory_id : UUID
        Any memory in the version chain.

    Returns
    -------
    list[MemoryResponse]
        All versions ordered by ``created_at`` ascending (oldest first).
    """
    sql = """
        WITH RECURSIVE chain AS (
            -- Anchor: the requested memory
            SELECT m.* FROM memories m WHERE m.id = :memory_id

            UNION

            -- Walk UP: find ancestors (what this memory superseded)
            SELECT parent.*
            FROM memories parent
            JOIN chain c ON c.supersedes_id = parent.id

            UNION

            -- Walk DOWN: find descendants (what superseded this memory)
            SELECT child.*
            FROM memories child
            JOIN chain c ON child.supersedes_id = c.id
        )
        SELECT * FROM chain
        ORDER BY created_at ASC
    """
    result = await session.execute(
        sa_text(sql), {"memory_id": str(memory_id)}
    )
    rows = result.fetchall()
    return [_row_to_response(row) for row in rows]


# ── Bitemporal snapshot ─────────────────────────────────────────────────────


async def get_temporal_snapshot(
    session: AsyncSession,
    user_id: str,
    as_of: datetime,
) -> list[MemoryResponse]:
    """
    Answer: "What did the system believe at time *as_of*?"

    This is a proper **bitemporal query** that intersects:

    * **System time** — the memory existed in the DB at *as_of*
      (``created_at <= as_of`` and not yet superseded).
    * **Valid time** — the fact was considered true at *as_of*
      (``valid_from <= as_of`` and not yet expired).

    Parameters
    ----------
    session : AsyncSession
        Active async session.
    user_id : str
        Scope to a specific user.
    as_of : datetime
        The reference timestamp for the snapshot.

    Returns
    -------
    list[MemoryResponse]
        Active memories ordered by importance descending.
    """
    sql = """
        SELECT *
        FROM memories
        WHERE user_id = :user_id
          AND created_at <= :as_of
          AND (superseded_at IS NULL OR superseded_at > :as_of)
          AND valid_from <= :as_of
          AND (valid_to IS NULL OR valid_to > :as_of)
          AND is_deleted = false
        ORDER BY importance DESC
    """
    result = await session.execute(
        sa_text(sql), {"user_id": user_id, "as_of": as_of}
    )
    rows = result.fetchall()
    return [_row_to_response(row) for row in rows]


# ── System-prompt generation ────────────────────────────────────────────────


async def get_system_prompt_context(
    session: AsyncSession,
    user_id: str,
    top_k: int = 10,
) -> str:
    """
    Build a formatted memory-context block for an LLM system prompt.

    Retrieves the **top-k** active memories ranked by ``decay_score`` and
    renders them as a compact Markdown section that can be injected directly
    into a system prompt.

    Format
    ------
    ::

        ## User Memory Context
        [Retrieved: 2025-05-20T12:00:00Z | Top 10 by relevance]

        1. [semantic|importance:0.80|decay:0.72] The user prefers dark-mode.
        2. ...

        ⚠ Stale memories (decay < 0.05): 3 memories flagged for review

    Parameters
    ----------
    session : AsyncSession
        Active async session.
    user_id : str
        User whose memories to include.
    top_k : int
        Number of top memories to include in the prompt.

    Returns
    -------
    str
        The fully formatted system-prompt memory block.
    """
    # Fetch top-k active memories by decay_score
    top_sql = """
        SELECT *
        FROM memories
        WHERE user_id = :user_id
          AND is_deleted = false
          AND superseded_at IS NULL
          AND valid_to IS NULL
        ORDER BY decay_score DESC
        LIMIT :top_k
    """
    top_result = await session.execute(
        sa_text(top_sql), {"user_id": user_id, "top_k": top_k}
    )
    top_rows = top_result.fetchall()

    # Count stale memories (decay below staleness_threshold)
    stale_sql = """
        SELECT COUNT(*) AS cnt
        FROM memories
        WHERE user_id = :user_id
          AND is_deleted = false
          AND superseded_at IS NULL
          AND valid_to IS NULL
          AND decay_score < :threshold
    """
    stale_result = await session.execute(
        sa_text(stale_sql),
        {"user_id": user_id, "threshold": settings.staleness_threshold},
    )
    stale_count: int = stale_result.scalar_one()

    # Bump access stats for the memories we're surfacing
    if top_rows:
        await _bump_access(session, [row.id for row in top_rows])

    # Format
    now = datetime.now(timezone.utc)
    lines: list[str] = [
        "## User Memory Context",
        f"[Retrieved: {now.isoformat()} | Top {len(top_rows)} by relevance]",
        "",
    ]
    for idx, row in enumerate(top_rows, start=1):
        lines.append(
            f"{idx}. [{row.memory_type}|importance:{row.importance:.2f}"
            f"|decay:{row.decay_score:.2f}] {row.content}"
        )

    lines.append("")
    lines.append(
        f"⚠ Stale memories (decay < {settings.staleness_threshold}): "
        f"{stale_count} memories flagged for review"
    )

    return "\n".join(lines)


# ── Private helpers ──────────────────────────────────────────────────────────


async def _bump_access(
    session: AsyncSession,
    memory_ids: list[uuid.UUID],
) -> None:
    """
    Increment ``access_count`` and set ``last_accessed_at`` for a batch of
    memory IDs.  This telemetry feeds the periodic decay recalculation job.
    """
    if not memory_ids:
        return

    await session.execute(
        sa_text(
            """
            UPDATE memories
            SET access_count    = access_count + 1,
                last_accessed_at = NOW()
            WHERE id = ANY(:ids)
            """
        ),
        {"ids": [str(mid) for mid in memory_ids]},
    )


def _row_to_response(row) -> MemoryResponse:
    """
    Convert a raw SQL row (from ``text()`` queries) into a
    :class:`MemoryResponse`.

    The row is accessed via attribute names that mirror the ``memories``
    table columns.  ``metadata`` maps to the Pydantic field via the
    ``validation_alias='metadata_'`` declared on the schema.
    """
    return MemoryResponse(
        id=row.id,
        user_id=row.user_id,
        content=row.content,
        memory_type=row.memory_type,
        tags=row.tags or [],
        source=row.source,
        metadata=row.metadata or {},
        importance=row.importance,
        access_count=row.access_count,
        last_accessed_at=row.last_accessed_at,
        decay_score=row.decay_score,
        created_at=row.created_at,
        superseded_at=row.superseded_at,
        valid_from=row.valid_from,
        valid_to=row.valid_to,
        is_deleted=row.is_deleted,
        deleted_at=row.deleted_at,
        supersedes_id=row.supersedes_id,
        contradiction_of=row.contradiction_of,
    )
