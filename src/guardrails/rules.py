"""Deterministic behavioral guardrails for the bitemporal memory system.

All rules are code-enforced, not prompt-based. This module provides
validation checks for memory writes including importance bounds,
PII detection, source provenance, rate limiting, content validation,
and memory type enforcement.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from dataclasses import dataclass, field


@dataclass
class GuardrailResult:
    """Result of a single guardrail check.

    Attributes:
        passed: Whether the check passed (True) or failed (False).
        rule: Identifier of the guardrail rule that was evaluated.
        message: Human-readable description of the result.
    """

    passed: bool
    rule: str
    message: str


class GuardrailEngine:
    """Deterministic behavioral guardrails for the memory system.

    All rules are code-enforced, not prompt-based. The engine validates
    memory writes against a set of deterministic rules and returns
    structured results indicating pass/fail status.

    Rules enforced:
        - importance_bounds: Importance must be in [0.0, 1.0]
        - pii_gate: Regex detection for emails, SSNs, phones, credit cards
        - source_provenance: Every memory must have a source field
        - rate_limit: Max 100 writes/min/user (configurable)
        - content_not_empty: Content must not be empty or whitespace
        - memory_type: Must be episodic, semantic, or procedural
    """

    VALID_MEMORY_TYPES = frozenset({"episodic", "semantic", "procedural"})

    PII_PATTERNS: dict[str, str] = {
        "email": r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}",
        "ssn": r"\b\d{3}-\d{2}-\d{4}\b",
        "phone": r"\b(?:\+?1[-.]?)?\(?\d{3}\)?[-.]?\d{3}[-.]?\d{4}\b",
        "credit_card": r"\b(?:\d{4}[-\s]?){3}\d{4}\b",
    }

    def __init__(self) -> None:
        self._write_counts: dict[str, list[float]] = defaultdict(list)

    def check_importance_bounds(self, importance: float) -> GuardrailResult:
        """Validate that importance is between 0.0 and 1.0 inclusive.

        Args:
            importance: The importance score to validate.

        Returns:
            GuardrailResult with passed=True if within bounds.
        """
        if 0.0 <= importance <= 1.0:
            return GuardrailResult(
                passed=True, rule="importance_bounds", message="OK"
            )
        return GuardrailResult(
            passed=False,
            rule="importance_bounds",
            message=f"Importance {importance} out of bounds [0.0, 1.0]",
        )

    def check_pii(self, content: str) -> GuardrailResult:
        """Check for potential PII in content.

        Scans content for email addresses, SSNs, phone numbers, and
        credit card numbers using regex patterns. Returns a warning
        but does NOT block the write — content is stored but flagged.

        Args:
            content: The memory content to scan.

        Returns:
            GuardrailResult with passed=True always (warning only).
            The message will contain detected PII types if any found.
        """
        found: list[str] = []
        for pii_type, pattern in self.PII_PATTERNS.items():
            if re.search(pattern, content):
                found.append(pii_type)

        if found:
            return GuardrailResult(
                passed=True,
                rule="pii_gate",
                message=(
                    f"\u26a0 Potential PII detected: {found}. "
                    f"Content was stored but flagged."
                ),
            )
        return GuardrailResult(passed=True, rule="pii_gate", message="OK")

    def check_source_provenance(self, source: str | None) -> GuardrailResult:
        """Validate that a source field is provided.

        Every memory must have provenance — where it came from.

        Args:
            source: The source string (e.g., 'user_explicit', 'inferred').

        Returns:
            GuardrailResult with passed=False if source is missing/empty.
        """
        if source and source.strip():
            return GuardrailResult(
                passed=True, rule="source_provenance", message="OK"
            )
        return GuardrailResult(
            passed=False,
            rule="source_provenance",
            message="Source provenance is required for every memory",
        )

    def check_rate_limit(
        self, user_id: str, max_per_minute: int = 100
    ) -> GuardrailResult:
        """Enforce maximum writes per minute per user.

        Uses an in-memory sliding window counter. Timestamps older
        than 60 seconds are pruned on each check.

        Args:
            user_id: The user identifier to rate-limit.
            max_per_minute: Maximum allowed writes per 60-second window.

        Returns:
            GuardrailResult with passed=False if limit exceeded.
        """
        now = time.time()
        # Prune timestamps older than 60 seconds
        self._write_counts[user_id] = [
            t for t in self._write_counts[user_id] if now - t < 60
        ]

        if len(self._write_counts[user_id]) >= max_per_minute:
            return GuardrailResult(
                passed=False,
                rule="rate_limit",
                message=f"Rate limit exceeded: {max_per_minute} writes/minute",
            )

        self._write_counts[user_id].append(now)
        return GuardrailResult(passed=True, rule="rate_limit", message="OK")

    def check_content_not_empty(self, content: str) -> GuardrailResult:
        """Validate that memory content is not empty or whitespace-only.

        Args:
            content: The memory content string.

        Returns:
            GuardrailResult with passed=False if content is empty.
        """
        if content and content.strip():
            return GuardrailResult(
                passed=True, rule="content_not_empty", message="OK"
            )
        return GuardrailResult(
            passed=False,
            rule="content_not_empty",
            message="Memory content cannot be empty",
        )

    def check_memory_type(self, memory_type: str) -> GuardrailResult:
        """Validate that memory type is one of the allowed values.

        Args:
            memory_type: The memory type string to validate.

        Returns:
            GuardrailResult with passed=False if type is invalid.
        """
        if memory_type in self.VALID_MEMORY_TYPES:
            return GuardrailResult(
                passed=True, rule="memory_type", message="OK"
            )
        return GuardrailResult(
            passed=False,
            rule="memory_type",
            message=(
                f"Invalid memory type: {memory_type}. "
                f"Must be one of {self.VALID_MEMORY_TYPES}"
            ),
        )

    def run_write_checks(
        self,
        content: str,
        importance: float,
        source: str,
        memory_type: str,
        user_id: str,
    ) -> list[GuardrailResult]:
        """Run all write-path guardrails.

        Executes each check in order and returns a list of results.
        If any result has ``passed=False``, the write should be rejected.

        Args:
            content: The memory content to store.
            importance: Importance score for the memory.
            source: Provenance of the memory.
            memory_type: Type classification of the memory.
            user_id: User performing the write.

        Returns:
            List of GuardrailResult objects from all checks.
        """
        results = [
            self.check_content_not_empty(content),
            self.check_importance_bounds(importance),
            self.check_source_provenance(source),
            self.check_memory_type(memory_type),
            self.check_rate_limit(user_id),
            self.check_pii(content),
        ]
        return results


# Module-level singleton for convenience
guardrail_engine = GuardrailEngine()
