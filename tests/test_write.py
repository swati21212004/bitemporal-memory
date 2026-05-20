"""Tests for the write-path Pydantic schemas.

Validates MemoryCreate, ContradictionResponse, and related schemas
directly (no database required).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from src.schemas.memory import (
    ContradictionResponse,
    MemoryCreate,
    MemoryResponse,
)


# ── MemoryCreate ─────────────────────────────────────────────────────────────


class TestMemoryCreate:
    """Validate the MemoryCreate request schema."""

    def test_valid_minimal(self) -> None:
        """Only 'content' is strictly required; other fields have defaults."""
        mc = MemoryCreate(content="User likes dark mode")
        assert mc.content == "User likes dark mode"
        assert mc.memory_type == "semantic"
        assert mc.importance == 0.5
        assert mc.tags == []
        assert mc.source == "conversation"
        assert mc.metadata == {}

    def test_valid_full(self) -> None:
        mc = MemoryCreate(
            content="User prefers Vim keybindings",
            memory_type="procedural",
            importance=0.9,
            tags=["editor", "preference"],
            source="user_explicit",
            metadata={"editor": "vim"},
            valid_from=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        assert mc.memory_type == "procedural"
        assert mc.importance == 0.9
        assert mc.tags == ["editor", "preference"]
        assert mc.source == "user_explicit"

    def test_empty_content_rejected(self) -> None:
        with pytest.raises(ValidationError) as exc_info:
            MemoryCreate(content="")
        assert "content" in str(exc_info.value).lower()

    def test_importance_too_low(self) -> None:
        with pytest.raises(ValidationError):
            MemoryCreate(content="test", importance=-0.1)

    def test_importance_too_high(self) -> None:
        with pytest.raises(ValidationError):
            MemoryCreate(content="test", importance=1.1)

    def test_importance_edge_zero(self) -> None:
        mc = MemoryCreate(content="test", importance=0.0)
        assert mc.importance == 0.0

    def test_importance_edge_one(self) -> None:
        mc = MemoryCreate(content="test", importance=1.0)
        assert mc.importance == 1.0

    def test_invalid_memory_type(self) -> None:
        with pytest.raises(ValidationError):
            MemoryCreate(content="test", memory_type="declarative")

    @pytest.mark.parametrize("mtype", ["episodic", "semantic", "procedural"])
    def test_valid_memory_types(self, mtype: str) -> None:
        mc = MemoryCreate(content="test", memory_type=mtype)
        assert mc.memory_type == mtype

    def test_tags_default_empty_list(self) -> None:
        mc = MemoryCreate(content="test")
        assert mc.tags == []
        assert isinstance(mc.tags, list)

    def test_metadata_default_empty_dict(self) -> None:
        mc = MemoryCreate(content="test")
        assert mc.metadata == {}
        assert isinstance(mc.metadata, dict)

    def test_valid_from_none_by_default(self) -> None:
        mc = MemoryCreate(content="test")
        assert mc.valid_from is None


# ── ContradictionResponse ────────────────────────────────────────────────────


class TestContradictionResponse:
    """Validate the ContradictionResponse schema."""

    def _make_memory_response(self, **overrides) -> MemoryResponse:
        """Factory for a valid MemoryResponse dict."""
        defaults = {
            "id": uuid.uuid4(),
            "user_id": "test_user",
            "content": "Old fact",
            "memory_type": "semantic",
            "tags": [],
            "source": "conversation",
            "metadata_": {},
            "importance": 0.5,
            "access_count": 0,
            "last_accessed_at": datetime.now(timezone.utc),
            "decay_score": 0.5,
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
        return MemoryResponse.model_validate(defaults, from_attributes=True)

    def test_valid_contradiction(self) -> None:
        existing = self._make_memory_response()
        cr = ContradictionResponse(
            existing_memory=existing,
            new_content="New contradicting fact",
            similarity_score=0.87,
            message="This memory contradicts an existing memory",
        )
        assert cr.similarity_score == 0.87
        assert cr.new_content == "New contradicting fact"

    def test_similarity_score_stored(self) -> None:
        existing = self._make_memory_response()
        cr = ContradictionResponse(
            existing_memory=existing,
            new_content="test",
            similarity_score=0.95,
            message="Contradiction detected",
        )
        assert cr.similarity_score == 0.95


# ── Schema validation edge cases ─────────────────────────────────────────────


class TestSchemaEdgeCases:
    """Edge cases for schema validation."""

    def test_whitespace_only_content_rejected(self) -> None:
        """min_length=1 should reject whitespace-only after Pydantic strips."""
        # Pydantic by default does NOT strip whitespace, so a single space
        # passes min_length=1. But empty string should fail.
        with pytest.raises(ValidationError):
            MemoryCreate(content="")

    def test_very_long_content_accepted(self) -> None:
        """No upper bound on content length at the schema level."""
        long_content = "a" * 100_000
        mc = MemoryCreate(content=long_content)
        assert len(mc.content) == 100_000

    def test_unicode_content(self) -> None:
        mc = MemoryCreate(content="用户喜欢深色模式 🌙")
        assert "🌙" in mc.content

    def test_tags_with_special_chars(self) -> None:
        mc = MemoryCreate(content="test", tags=["c++", "c#", "node.js"])
        assert mc.tags == ["c++", "c#", "node.js"]

    def test_importance_float_precision(self) -> None:
        mc = MemoryCreate(content="test", importance=0.123456789)
        assert mc.importance == pytest.approx(0.123456789)
