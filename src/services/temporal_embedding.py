"""
Sinusoidal Time Embedding Service.

Computes a periodic temporal encoding for elapsed time offsets, mirroring
transformer positional encodings. Converts an elapsed duration in seconds
into a high-dimensional vector.
"""

from __future__ import annotations

import math


def compute_time_embedding(delta_seconds: float, dimensions: int = 1536) -> list[float]:
    """Compute a sinusoidal time embedding vector for a given duration in seconds.

    PE(dt)_{2i}   = sin(dt / 10000^(2i/d))
    PE(dt)_{2i+1} = cos(dt / 10000^(2i/d))

    Args:
        delta_seconds: The elapsed time in seconds (can be positive or negative).
        dimensions: The size of the output embedding vector (default: 1536).

    Returns:
        A list of float values representing the sinusoidal temporal encoding.
    """
    if dimensions <= 0:
        raise ValueError("Dimensions must be a positive integer.")

    embedding = [0.0] * dimensions
    half_dim = dimensions // 2

    for i in range(half_dim):
        exponent = (2 * i) / dimensions
        divisor = 10000.0 ** exponent
        
        # Avoid DivisionByZero if divisor is somehow 0 (mathematically impossible but safe guard)
        if divisor == 0:
            val = 0.0
        else:
            val = delta_seconds / divisor

        embedding[2 * i] = math.sin(val)
        embedding[2 * i + 1] = math.cos(val)

    # Handle odd dimensions gracefully
    if dimensions % 2 != 0:
        exponent = (dimensions - 1) / dimensions
        divisor = 10000.0 ** exponent
        val = delta_seconds / divisor if divisor != 0 else 0.0
        embedding[-1] = math.sin(val)

    return embedding
