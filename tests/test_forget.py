"""Tests for the forget-path Pydantic schemas.

Validates ForgetRequest and ForgetByQueryRequest schemas directly
(no database required).
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import ValidationError

from src.schemas.memory import ForgetByQueryRequest, ForgetRequest

# ── ForgetRequest ────────────────────────────────────────────────────────────


class TestForgetRequest:
    """Validate the ForgetRequest schema."""

    def test_valid_with_memory_id(self) -> None:
        mid = uuid.uuid4()
        fr = ForgetRequest(memory_id=mid)
        assert fr.memory_id == mid
        assert fr.query is None
        assert fr.reason is None

    def test_valid_with_query(self) -> None:
        fr = ForgetRequest(query="forget my address")
        assert fr.query == "forget my address"
        assert fr.memory_id is None

    def test_valid_with_both(self) -> None:
        mid = uuid.uuid4()
        fr = ForgetRequest(memory_id=mid, query="forget this")
        assert fr.memory_id == mid
        assert fr.query == "forget this"

    def test_requires_at_least_one(self) -> None:
        """Neither memory_id nor query → should fail."""
        with pytest.raises(ValidationError) as exc_info:
            ForgetRequest()
        assert "memory_id" in str(exc_info.value) or "query" in str(exc_info.value)

    def test_none_values_also_rejected(self) -> None:
        """Explicitly passing None for both should also fail."""
        with pytest.raises(ValidationError):
            ForgetRequest(memory_id=None, query=None)

    def test_reason_optional(self) -> None:
        fr = ForgetRequest(memory_id=uuid.uuid4(), reason="User requested")
        assert fr.reason == "User requested"

    def test_reason_none_by_default(self) -> None:
        fr = ForgetRequest(query="forget this")
        assert fr.reason is None

    def test_valid_uuid_format(self) -> None:
        """A valid UUID string should be accepted."""
        uid = "550e8400-e29b-41d4-a716-446655440000"
        fr = ForgetRequest(memory_id=uid)  # type: ignore[arg-type]
        assert str(fr.memory_id) == uid


# ── ForgetByQueryRequest ─────────────────────────────────────────────────────


class TestForgetByQueryRequest:
    """Validate the ForgetByQueryRequest schema."""

    def test_valid_minimal(self) -> None:
        fr = ForgetByQueryRequest(query="forget my ex")
        assert fr.query == "forget my ex"
        assert fr.threshold == 0.8  # default
        assert fr.reason is None

    def test_valid_full(self) -> None:
        fr = ForgetByQueryRequest(
            query="forget all work memories",
            threshold=0.9,
            reason="Moving on",
        )
        assert fr.threshold == 0.9
        assert fr.reason == "Moving on"

    def test_empty_query_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ForgetByQueryRequest(query="")

    def test_threshold_lower_bound(self) -> None:
        fr = ForgetByQueryRequest(query="test", threshold=0.0)
        assert fr.threshold == 0.0

    def test_threshold_upper_bound(self) -> None:
        fr = ForgetByQueryRequest(query="test", threshold=1.0)
        assert fr.threshold == 1.0

    def test_threshold_below_range(self) -> None:
        with pytest.raises(ValidationError):
            ForgetByQueryRequest(query="test", threshold=-0.1)

    def test_threshold_above_range(self) -> None:
        with pytest.raises(ValidationError):
            ForgetByQueryRequest(query="test", threshold=1.1)

    def test_default_threshold(self) -> None:
        fr = ForgetByQueryRequest(query="test")
        assert fr.threshold == 0.8

    def test_reason_optional(self) -> None:
        fr = ForgetByQueryRequest(query="test", reason="spring cleaning")
        assert fr.reason == "spring cleaning"
