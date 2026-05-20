"""Shared pytest fixtures for the bitemporal memory test suite.

Provides mock embedding services to avoid hitting the real OpenAI API
during tests, plus common test data factories.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ── Constants ────────────────────────────────────────────────────────────────

MOCK_EMBEDDING_DIM = 1536
MOCK_EMBEDDING_VECTOR = [0.1] * MOCK_EMBEDDING_DIM


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture()
def mock_embedding() -> list[float]:
    """Return a deterministic 1536-dimensional embedding vector.

    Useful when tests need a concrete vector without hitting OpenAI.
    """
    return MOCK_EMBEDDING_VECTOR.copy()


@pytest.fixture()
def mock_embedding_service():
    """Patch ``src.services.embedding.get_embedding_service`` with a mock.

    The mock's ``embed`` coroutine always resolves to the standard
    1536-dim test vector.  The fixture yields the mock service so tests
    can inspect calls or customise return values.

    Usage::

        def test_something(mock_embedding_service):
            # The embedding service is already patched in scope.
            mock_embedding_service.embed.return_value = [0.5] * 1536
    """
    service = MagicMock()
    service.embed = AsyncMock(return_value=MOCK_EMBEDDING_VECTOR.copy())

    with patch(
        "src.services.embedding.get_embedding_service",
        return_value=service,
    ):
        yield service
