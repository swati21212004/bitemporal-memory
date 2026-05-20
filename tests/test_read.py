"""Tests for the read-path Pydantic schemas.

Validates MemorySearchQuery, TemporalQuery, and MemoryResponse
schemas directly (no database required).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.memory import (
    MemoryResponse,
    MemorySearchQuery,
    TemporalQuery,
)


# ── MemorySearchQuery ────────────────────────────────────────────────────────


class TestMemorySearchQuery:
    """Validate the MemorySearchQuery schema."""

    def test_valid_minimal(self) -> None:
        q = MemorySearchQuery(query="What are user preferences?")
        assert q.query == "What are user preferences?"
        assert q.top_k == 10
        assert q.memory_type is None
        assert q.tags is None

    def test_valid_full(self) -> None:
        q = MemorySearchQuery(
            query="UI preferences",
            top_k=5,
            memory_type="semantic",
            tags=["preference", "ui"],
        )
        assert q.top_k == 5
        assert q.memory_type == "semantic"
        assert q.tags == ["preference", "ui"]

    def test_empty_query_rejected(self) -> None:
        with pytest.raises(ValidationError):
            MemorySearchQuery(query="")

    def test_top_k_minimum(self) -> None:
        q = MemorySearchQuery(query="test", top_k=1)
        assert q.top_k == 1

    def test_top_k_maximum(self) -> None:
        q = MemorySearchQuery(query="test", top_k=100)
        assert q.top_k == 100

    def test_top_k_below_minimum(self) -> None:
        with pytest.raises(ValidationError):
            MemorySearchQuery(query="test", top_k=0)

    def test_top_k_above_maximum(self) -> None:
        with pytest.raises(ValidationError):
            MemorySearchQuery(query="test", top_k=101)

    def test_default_top_k(self) -> None:
        q = MemorySearchQuery(query="test")
        assert q.top_k == 10

    def test_tags_filter_none_by_default(self) -> None:
        q = MemorySearchQuery(query="test")
        assert q.tags is None

    def test_memory_type_filter_none_by_default(self) -> None:
        q = MemorySearchQuery(query="test")
        assert q.memory_type is None


# ── TemporalQuery ────────────────────────────────────────────────────────────


class TestTemporalQuery:
    """Validate the TemporalQuery schema."""

    def test_valid(self) -> None:
        tq = TemporalQuery(
            as_of=datetime(2025, 6, 15, 12, 0, tzinfo=timezone.utc),
            user_id="alice",
        )
        assert tq.as_of.year == 2025
        assert tq.user_id == "alice"

    def test_default_user_id(self) -> None:
        tq = TemporalQuery(
            as_of=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert tq.user_id == "default"

    def test_as_of_required(self) -> None:
        with pytest.raises(ValidationError):
            TemporalQuery()  # type: ignore[call-arg]

    def test_timezone_aware_datetime(self) -> None:
        dt = datetime(2025, 3, 15, 10, 30, tzinfo=timezone.utc)
        tq = TemporalQuery(as_of=dt)
        assert tq.as_of.tzinfo is not None


# ── MemoryResponse ───────────────────────────────────────────────────────────


class TestMemoryResponse:
    """Validate the MemoryResponse schema with from_attributes."""

    def _make_attrs(self, **overrides) -> dict:
        """Return a dict that simulates ORM attribute access."""
        defaults = {
            "id": uuid.uuid4(),
            "user_id": "default",
            "content": "User prefers dark mode",
            "memory_type": "semantic",
            "tags": ["preference", "ui"],
            "source": "user_explicit",
            "metadata_": {"key": "value"},
            "importance": 0.8,
            "access_count": 5,
            "last_accessed_at": datetime.now(timezone.utc),
            "decay_score": 0.45,
            "created_at": datetime.now(timezone.utc),
            "superseded_at": None,
            "valid_from": datetime.now(timezone.utc),
            "valid_to": None,
            "is_deleted": False,
            "deleted_at": None,
            "supersedes_id": None,
            "contradiction_of": None,
        }
        defaults.update(overrides)
        return defaults

    def test_from_attributes(self) -> None:
        attrs = self._make_attrs()
        mr = MemoryResponse.model_validate(attrs, from_attributes=True)
        assert mr.content == "User prefers dark mode"
        assert mr.importance == 0.8
        assert mr.tags == ["preference", "ui"]

    def test_metadata_alias(self) -> None:
        """The ORM uses 'metadata_' to avoid shadowing Python's builtins;
        the schema should map it to 'metadata' via validation_alias."""
        attrs = self._make_attrs(metadata_={"editor": "vim"})
        mr = MemoryResponse.model_validate(attrs, from_attributes=True)
        assert mr.metadata == {"editor": "vim"}

    def test_soft_deleted_memory(self) -> None:
        now = datetime.now(timezone.utc)
        attrs = self._make_attrs(
            is_deleted=True,
            deleted_at=now,
            valid_to=now,
        )
        mr = MemoryResponse.model_validate(attrs, from_attributes=True)
        assert mr.is_deleted is True
        assert mr.deleted_at == now
        assert mr.valid_to == now

    def test_superseded_memory(self) -> None:
        now = datetime.now(timezone.utc)
        original_id = uuid.uuid4()
        attrs = self._make_attrs(
            supersedes_id=original_id,
            superseded_at=now,
        )
        mr = MemoryResponse.model_validate(attrs, from_attributes=True)
        assert mr.supersedes_id == original_id
        assert mr.superseded_at == now

    def test_all_fields_populated(self) -> None:
        now = datetime.now(timezone.utc)
        original_id = uuid.uuid4()
        contradiction_id = uuid.uuid4()
        attrs = self._make_attrs(
            supersedes_id=original_id,
            contradiction_of=contradiction_id,
            superseded_at=now,
            valid_to=now,
            is_deleted=True,
            deleted_at=now,
        )
        mr = MemoryResponse.model_validate(attrs, from_attributes=True)
        assert mr.supersedes_id == original_id
        assert mr.contradiction_of == contradiction_id
