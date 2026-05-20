"""Tests for the deterministic guardrail engine.

Covers every individual check method as well as the composite
``run_write_checks`` pipeline.
"""

from __future__ import annotations

import time

import pytest

from src.guardrails.rules import GuardrailEngine, GuardrailResult


# ── Helpers ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def engine() -> GuardrailEngine:
    """Return a fresh GuardrailEngine per test (isolated rate-limit state)."""
    return GuardrailEngine()


# ── check_importance_bounds ──────────────────────────────────────────────────


class TestImportanceBounds:
    """Importance must be in [0.0, 1.0]."""

    def test_valid_mid_range(self, engine: GuardrailEngine) -> None:
        result = engine.check_importance_bounds(0.5)
        assert result.passed is True
        assert result.rule == "importance_bounds"

    def test_edge_lower_bound(self, engine: GuardrailEngine) -> None:
        result = engine.check_importance_bounds(0.0)
        assert result.passed is True

    def test_edge_upper_bound(self, engine: GuardrailEngine) -> None:
        result = engine.check_importance_bounds(1.0)
        assert result.passed is True

    def test_below_lower_bound(self, engine: GuardrailEngine) -> None:
        result = engine.check_importance_bounds(-0.1)
        assert result.passed is False
        assert "out of bounds" in result.message

    def test_above_upper_bound(self, engine: GuardrailEngine) -> None:
        result = engine.check_importance_bounds(1.5)
        assert result.passed is False
        assert "out of bounds" in result.message

    def test_negative_large(self, engine: GuardrailEngine) -> None:
        result = engine.check_importance_bounds(-100.0)
        assert result.passed is False

    def test_positive_large(self, engine: GuardrailEngine) -> None:
        result = engine.check_importance_bounds(999.0)
        assert result.passed is False


# ── check_pii ────────────────────────────────────────────────────────────────


class TestPIIGate:
    """PII detection should flag but never block writes."""

    def test_clean_text(self, engine: GuardrailEngine) -> None:
        result = engine.check_pii("User prefers dark mode")
        assert result.passed is True
        assert result.message == "OK"

    def test_detects_email(self, engine: GuardrailEngine) -> None:
        result = engine.check_pii("Contact me at alice@example.com")
        assert result.passed is True  # PII gate warns, does NOT block
        assert "email" in result.message
        assert "PII detected" in result.message

    def test_detects_ssn(self, engine: GuardrailEngine) -> None:
        result = engine.check_pii("My SSN is 123-45-6789")
        assert result.passed is True
        assert "ssn" in result.message

    def test_detects_phone(self, engine: GuardrailEngine) -> None:
        result = engine.check_pii("Call me at (555) 123-4567")
        assert result.passed is True
        assert "phone" in result.message

    def test_detects_credit_card(self, engine: GuardrailEngine) -> None:
        result = engine.check_pii("Card: 4111-1111-1111-1111")
        assert result.passed is True
        assert "credit_card" in result.message

    def test_detects_multiple_pii(self, engine: GuardrailEngine) -> None:
        result = engine.check_pii(
            "Email: a@b.com, SSN: 123-45-6789, Phone: 555-123-4567"
        )
        assert result.passed is True
        assert "email" in result.message
        assert "ssn" in result.message
        assert "phone" in result.message

    def test_credit_card_with_spaces(self, engine: GuardrailEngine) -> None:
        result = engine.check_pii("Card: 4111 1111 1111 1111")
        assert result.passed is True
        assert "credit_card" in result.message


# ── check_source_provenance ──────────────────────────────────────────────────


class TestSourceProvenance:
    """Every memory must have a non-empty source."""

    def test_valid_source(self, engine: GuardrailEngine) -> None:
        result = engine.check_source_provenance("user_explicit")
        assert result.passed is True

    def test_empty_string(self, engine: GuardrailEngine) -> None:
        result = engine.check_source_provenance("")
        assert result.passed is False
        assert "Source provenance" in result.message

    def test_whitespace_only(self, engine: GuardrailEngine) -> None:
        result = engine.check_source_provenance("   ")
        assert result.passed is False

    def test_none(self, engine: GuardrailEngine) -> None:
        result = engine.check_source_provenance(None)
        assert result.passed is False


# ── check_rate_limit ─────────────────────────────────────────────────────────


class TestRateLimit:
    """Max writes per minute per user."""

    def test_under_limit(self, engine: GuardrailEngine) -> None:
        result = engine.check_rate_limit("user1", max_per_minute=100)
        assert result.passed is True

    def test_at_limit(self, engine: GuardrailEngine) -> None:
        """Fill to exactly the limit, then the next call should fail."""
        for _ in range(5):
            result = engine.check_rate_limit("user2", max_per_minute=5)
        # 5 successful writes; the 6th should be blocked
        result = engine.check_rate_limit("user2", max_per_minute=5)
        assert result.passed is False
        assert "Rate limit exceeded" in result.message

    def test_over_limit(self, engine: GuardrailEngine) -> None:
        for _ in range(3):
            engine.check_rate_limit("user3", max_per_minute=3)
        result = engine.check_rate_limit("user3", max_per_minute=3)
        assert result.passed is False

    def test_different_users_independent(self, engine: GuardrailEngine) -> None:
        """Rate limits should be per-user, not global."""
        for _ in range(3):
            engine.check_rate_limit("userA", max_per_minute=3)
        # userA is at limit
        result_a = engine.check_rate_limit("userA", max_per_minute=3)
        assert result_a.passed is False
        # userB should still be fine
        result_b = engine.check_rate_limit("userB", max_per_minute=3)
        assert result_b.passed is True

    def test_single_write_succeeds(self, engine: GuardrailEngine) -> None:
        result = engine.check_rate_limit("new_user", max_per_minute=100)
        assert result.passed is True
        assert result.message == "OK"


# ── check_content_not_empty ──────────────────────────────────────────────────


class TestContentNotEmpty:
    """Content must not be empty or whitespace-only."""

    def test_valid_content(self, engine: GuardrailEngine) -> None:
        result = engine.check_content_not_empty("User likes Python")
        assert result.passed is True

    def test_empty_string(self, engine: GuardrailEngine) -> None:
        result = engine.check_content_not_empty("")
        assert result.passed is False
        assert "cannot be empty" in result.message

    def test_whitespace_only(self, engine: GuardrailEngine) -> None:
        result = engine.check_content_not_empty("   \t\n  ")
        assert result.passed is False


# ── check_memory_type ────────────────────────────────────────────────────────


class TestMemoryType:
    """Memory type must be one of the valid enum values."""

    @pytest.mark.parametrize("mtype", ["episodic", "semantic", "procedural"])
    def test_valid_types(self, engine: GuardrailEngine, mtype: str) -> None:
        result = engine.check_memory_type(mtype)
        assert result.passed is True

    def test_invalid_type(self, engine: GuardrailEngine) -> None:
        result = engine.check_memory_type("declarative")
        assert result.passed is False
        assert "Invalid memory type" in result.message

    def test_empty_type(self, engine: GuardrailEngine) -> None:
        result = engine.check_memory_type("")
        assert result.passed is False

    def test_case_sensitive(self, engine: GuardrailEngine) -> None:
        """Types are case-sensitive; 'Episodic' should fail."""
        result = engine.check_memory_type("Episodic")
        assert result.passed is False


# ── run_write_checks ─────────────────────────────────────────────────────────


class TestRunWriteChecks:
    """Integration tests for the full write-check pipeline."""

    def test_all_pass(self, engine: GuardrailEngine) -> None:
        results = engine.run_write_checks(
            content="User prefers dark mode",
            importance=0.7,
            source="user_explicit",
            memory_type="semantic",
            user_id="test_user",
        )
        assert all(r.passed for r in results)
        assert len(results) == 6  # 6 checks in the pipeline

    def test_one_fails_importance(self, engine: GuardrailEngine) -> None:
        results = engine.run_write_checks(
            content="Some fact",
            importance=1.5,  # Out of bounds
            source="user_explicit",
            memory_type="semantic",
            user_id="test_user",
        )
        failed = [r for r in results if not r.passed]
        assert len(failed) == 1
        assert failed[0].rule == "importance_bounds"

    def test_multiple_failures(self, engine: GuardrailEngine) -> None:
        results = engine.run_write_checks(
            content="",  # Empty
            importance=2.0,  # Out of bounds
            source="",  # Missing
            memory_type="invalid",  # Bad type
            user_id="test_user",
        )
        failed = [r for r in results if not r.passed]
        assert len(failed) == 4

    def test_pii_flagged_but_passes(self, engine: GuardrailEngine) -> None:
        """PII detection should warn but not block."""
        results = engine.run_write_checks(
            content="Email is test@example.com",
            importance=0.5,
            source="conversation",
            memory_type="episodic",
            user_id="test_user",
        )
        # All should pass (PII is a warning)
        assert all(r.passed for r in results)
        # But the PII check message should contain the warning
        pii_result = next(r for r in results if r.rule == "pii_gate")
        assert "PII detected" in pii_result.message

    def test_returns_guardrail_result_objects(self, engine: GuardrailEngine) -> None:
        results = engine.run_write_checks(
            content="test",
            importance=0.5,
            source="test",
            memory_type="semantic",
            user_id="test_user",
        )
        for r in results:
            assert isinstance(r, GuardrailResult)
            assert isinstance(r.passed, bool)
            assert isinstance(r.rule, str)
            assert isinstance(r.message, str)
