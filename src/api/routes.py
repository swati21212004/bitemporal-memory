"""
Bitemporal AI Memory System — FastAPI route definitions.

Exposes two routers:

* ``router`` (``/memories``) — all memory CRUD, search, temporal, and forget
  endpoints.
* ``health_router`` — a lightweight ``/health`` probe for load-balancers and
  orchestrators.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Union
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from src.database import get_session
from src.schemas.memory import (
    ContradictionResponse,
    ForgetByQueryRequest,
    MemoryCreate,
    MemoryResponse,
    MemorySearchQuery,
)
from src.services import memory_forget, memory_read, memory_write

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Request / response helpers (route-specific models)
# ---------------------------------------------------------------------------

class ForgetReasonBody(BaseModel):
    """Optional body for the single-memory forget endpoint."""
    reason: str | None = Field(default=None, description="Reason for forgetting this memory")


class ContradictionResolution(BaseModel):
    """How to resolve a detected contradiction."""
    strategy: str = Field(
        ...,
        description="Resolution strategy: 'keep_existing', 'supersede', or 'keep_both'",
    )


class ResolveContradictionRequest(BaseModel):
    """Request body for the contradiction resolution endpoint."""
    existing_id: UUID = Field(..., description="UUID of the existing (contradicted) memory")
    resolution: ContradictionResolution = Field(..., description="Chosen resolution strategy")
    new_data: MemoryCreate = Field(..., description="The new memory data that triggered the contradiction")


# ---------------------------------------------------------------------------
# Health router
# ---------------------------------------------------------------------------

health_router = APIRouter(tags=["health"])


@health_router.get(
    "/health",
    summary="Health check",
    description="Lightweight liveness probe.",
)
async def health_check() -> dict:
    """Return a simple health-check payload."""
    return {"status": "healthy", "service": "bitemporal-memory"}


# ---------------------------------------------------------------------------
# Memory router
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/memories", tags=["memories"])


# 1. POST / — Create a new memory
@router.post(
    "/",
    response_model=Union[MemoryResponse, ContradictionResponse],
    status_code=201,
    summary="Write a memory",
    description="Store a new memory.  Returns 201 on success or 409 if a contradiction is detected.",
)
async def create_memory(
    data: MemoryCreate,
    user_id: str = Query(default="default", description="User identifier"),
    session: AsyncSession = Depends(get_session),
):
    """Write a new memory, checking for contradictions and duplicates."""
    result = await memory_write.write_memory(session, data, user_id)

    if isinstance(result, ContradictionResponse):
        raise HTTPException(status_code=409, detail=result.model_dump())

    return result


# 2. POST /search — Semantic search
@router.post(
    "/search",
    response_model=list[MemoryResponse],
    summary="Search memories",
    description="Semantic search across the user's active memories.",
)
async def search_memories(
    body: MemorySearchQuery,
    user_id: str = Query(default="default", description="User identifier"),
    session: AsyncSession = Depends(get_session),
) -> list[MemoryResponse]:
    """Search memories by semantic similarity."""
    return await memory_read.search_memories(
        session,
        query=body.query,
        user_id=user_id,
        top_k=body.top_k,
        memory_type=body.memory_type,
        tags=body.tags,
    )


# 3. GET /temporal — Temporal snapshot
#    (defined BEFORE /{memory_id} to avoid path-param collision)
@router.get(
    "/temporal",
    response_model=list[MemoryResponse],
    summary="Temporal snapshot",
    description="Retrieve the state of all memories as of a specific point in time.",
)
async def temporal_snapshot(
    as_of: datetime = Query(..., description="Point-in-time for the snapshot (ISO-8601)"),
    user_id: str = Query(default="default", description="User identifier"),
    session: AsyncSession = Depends(get_session),
) -> list[MemoryResponse]:
    """Get a bitemporal snapshot of memories at a given point in time."""
    return await memory_read.get_temporal_snapshot(session, user_id=user_id, as_of=as_of)


# 4. GET /system-prompt — System-prompt context
@router.get(
    "/system-prompt",
    summary="System prompt context",
    description="Build a text block suitable for injection into an LLM system prompt.",
)
async def get_system_prompt(
    user_id: str = Query(default="default", description="User identifier"),
    top_k: int = Query(default=10, ge=1, le=100, description="Max memories to include"),
    session: AsyncSession = Depends(get_session),
) -> str:
    """Generate a system-prompt context string from the user's top memories."""
    return await memory_read.get_system_prompt_context(session, user_id=user_id, top_k=top_k)


# 5. POST /forget-by-query — Forget by semantic query
@router.post(
    "/forget-by-query",
    summary="Forget by query",
    description=(
        "Find memories matching a semantic query and optionally soft-delete them. "
        "Use confirm=false to preview matches before committing."
    ),
)
async def forget_by_query(
    body: ForgetByQueryRequest,
    user_id: str = Query(default="default", description="User identifier"),
    confirm: bool = Query(default=False, description="Set to true to execute the deletion"),
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Preview or execute a query-based forget operation."""
    return await memory_forget.forget_by_query(
        session,
        query=body.query,
        user_id=user_id,
        threshold=body.threshold,
        reason=body.reason,
        confirm=confirm,
    )


# 6. POST /resolve-contradiction — Resolve a detected contradiction
@router.post(
    "/resolve-contradiction",
    response_model=MemoryResponse,
    summary="Resolve contradiction",
    description="Resolve a previously detected contradiction between two memories.",
)
async def resolve_contradiction(
    body: ResolveContradictionRequest,
    user_id: str = Query(default="default", description="User identifier"),
    session: AsyncSession = Depends(get_session),
) -> MemoryResponse:
    """Resolve a contradiction using the chosen strategy."""
    return await memory_write.resolve_contradiction(
        session,
        existing_id=body.existing_id,
        resolution=body.resolution.strategy,
        new_data=body.new_data,
        user_id=user_id,
    )


# 7. GET /{memory_id} — Get a single memory
@router.get(
    "/{memory_id}",
    response_model=MemoryResponse,
    summary="Get memory by ID",
    description="Retrieve a single memory by its UUID.",
)
async def get_memory(
    memory_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> MemoryResponse:
    """Fetch a single memory by its primary key."""
    memory = await memory_read.get_memory_by_id(session, memory_id)
    if memory is None:
        raise HTTPException(status_code=404, detail=f"Memory {memory_id} not found")
    return memory


# 8. GET /{memory_id}/history — Get version history
@router.get(
    "/{memory_id}/history",
    response_model=list[MemoryResponse],
    summary="Memory history",
    description="Retrieve the full version history (lineage) of a memory.",
)
async def get_history(
    memory_id: UUID,
    session: AsyncSession = Depends(get_session),
) -> list[MemoryResponse]:
    """Get the bitemporal version history for a memory."""
    return await memory_read.get_memory_history(session, memory_id)


# 9. POST /{memory_id}/forget — Forget a single memory
@router.post(
    "/{memory_id}/forget",
    response_model=MemoryResponse,
    summary="Forget memory",
    description="Soft-delete a single memory by its UUID.",
)
async def forget_memory(
    memory_id: UUID,
    body: ForgetReasonBody | None = None,
    user_id: str = Query(default="default", description="User identifier"),
    session: AsyncSession = Depends(get_session),
) -> MemoryResponse:
    """Soft-delete a single memory."""
    reason = body.reason if body else None
    try:
        return await memory_forget.forget_by_id(
            session,
            memory_id=memory_id,
            user_id=user_id,
            reason=reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
