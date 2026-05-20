"""Guardrails engine for the bitemporal memory system.

Provides deterministic, code-enforced behavioral guardrails
including PII detection, rate limiting, importance bounds,
and source provenance validation.
"""

from src.guardrails.rules import GuardrailEngine, GuardrailResult, guardrail_engine

__all__ = ["GuardrailEngine", "GuardrailResult", "guardrail_engine"]
