"""
Bitemporal AI Memory System — Configuration.

All settings are loaded from environment variables with sensible defaults.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application configuration via environment variables."""

    # ── Database ──────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://memory_user:memory_pass@localhost:5432/memory_db",
        description="Async PostgreSQL connection string",
    )

    # ── OpenAI ────────────────────────────────────────────────────────────
    openai_api_key: str = Field(
        default="",
        description="OpenAI API key for embeddings",
    )
    embedding_model: str = Field(
        default="text-embedding-3-small",
        description="OpenAI embedding model name",
    )
    embedding_dimensions: int = Field(
        default=1536,
        description="Embedding vector dimensionality",
    )

    # ── Retrieval Weights ─────────────────────────────────────────────────
    semantic_weight: float = Field(
        default=0.6,
        description="Weight for semantic similarity in hybrid scoring",
    )
    decay_weight: float = Field(
        default=0.4,
        description="Weight for decay score in hybrid scoring",
    )

    # ── Decay Job ─────────────────────────────────────────────────────────
    decay_job_interval_minutes: int = Field(
        default=15,
        description="How often the decay recalculation job runs (minutes)",
    )

    # ── Guardrails ────────────────────────────────────────────────────────
    contradiction_threshold: float = Field(
        default=0.85,
        description="Cosine similarity threshold for contradiction detection",
    )
    deduplication_threshold: float = Field(
        default=0.95,
        description="Cosine similarity threshold for duplicate rejection",
    )
    max_writes_per_minute: int = Field(
        default=100,
        description="Rate limit: max memory writes per minute per user",
    )
    staleness_threshold: float = Field(
        default=0.05,
        description="Decay score below which memories are flagged as stale",
    )

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
