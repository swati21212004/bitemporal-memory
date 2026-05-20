"""
Bitemporal AI Memory System — Services package.

Contains the core business-logic services:

* **embedding** — vector embedding via OpenAI
* **temporal_embedding** — sinusoidal temporal vector encoding
* **memory_write** — create, deduplicate, and resolve contradictions
* **memory_read** — search, temporal queries, and system-prompt generation
"""

from src.services.temporal_embedding import compute_time_embedding

__all__ = ["compute_time_embedding"]

