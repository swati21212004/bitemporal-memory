"""
Tests for the Sinusoidal Time Embedding Service.

Validates the mathematical computation of sinusoidal time encodings and
bounds of values, plus basic endpoint routing where possible.
"""

from __future__ import annotations

import math
import pytest

from src.services.temporal_embedding import compute_time_embedding


class TestTemporalEmbedding:
    """Validate sinusoidal temporal embedding computations."""

    def test_dimensions_match_request(self) -> None:
        """Verify that the returned embedding has the requested dimensions."""
        dims = 1536
        embedding = compute_time_embedding(delta_seconds=3600.0, dimensions=dims)
        assert len(embedding) == dims

        dims_small = 16
        embedding_small = compute_time_embedding(delta_seconds=3600.0, dimensions=dims_small)
        assert len(embedding_small) == dims_small

    def test_bounds_and_structure(self) -> None:
        """Verify values are mathematically correct sinusoidal bounds (-1.0 to 1.0) and patterns."""
        embedding = compute_time_embedding(delta_seconds=12345.67, dimensions=128)
        for val in embedding:
            assert -1.0 <= val <= 1.0

        # Check standard transformer index logic:
        # i = 0 -> PE_0 = sin(dt), PE_1 = cos(dt)
        dt = 500.0
        embedding_0 = compute_time_embedding(delta_seconds=dt, dimensions=4)
        assert math.isclose(embedding_0[0], math.sin(dt))
        assert math.isclose(embedding_0[1], math.cos(dt))

        # Check i = 1 -> PE_2 = sin(dt / 10000**(2/4)), PE_3 = cos(dt / 10000**(2/4))
        # 10000**(2/4) = sqrt(10000) = 100
        assert math.isclose(embedding_0[2], math.sin(dt / 100.0))
        assert math.isclose(embedding_0[3], math.cos(dt / 100.0))

    def test_invalid_dimensions(self) -> None:
        """Verify that invalid dimension requests raise ValueErrors."""
        with pytest.raises(ValueError):
            compute_time_embedding(delta_seconds=60.0, dimensions=0)

        with pytest.raises(ValueError):
            compute_time_embedding(delta_seconds=60.0, dimensions=-12)

    def test_odd_dimensions_graceful_handling(self) -> None:
        """Verify odd dimension vectors are handled correctly without crash."""
        embedding = compute_time_embedding(delta_seconds=60.0, dimensions=5)
        assert len(embedding) == 5
