"""Initial schema — execute sql/schema.sql.

Revision ID: 001
Revises: None
Create Date: 2024-01-01 00:00:00.000000+00:00

Applies the full initial schema (pgvector extension, memory_type enum,
memories table, memory_audit_log table, and all indexes) by reading and
executing the hand-written ``sql/schema.sql`` file.

Downgrade drops all created objects in reverse dependency order.
"""
from __future__ import annotations

from pathlib import Path
from typing import Sequence, Union

from alembic import op

# ---------------------------------------------------------------------------
# Revision identifiers
# ---------------------------------------------------------------------------

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read_schema_sql() -> str:
    """Read the ``sql/schema.sql`` file relative to the project root.

    The project root is assumed to be two levels above this file:
    ``alembic/versions/001_initial_schema.py`` → project root.
    """
    schema_path = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"
    if not schema_path.exists():
        raise FileNotFoundError(
            f"Schema file not found at {schema_path}. "
            "Ensure sql/schema.sql exists in the project root."
        )
    return schema_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Migration
# ---------------------------------------------------------------------------

def upgrade() -> None:
    """Apply the full initial schema from sql/schema.sql."""
    sql = _read_schema_sql()
    op.execute(sql)


def downgrade() -> None:
    """Drop all objects created by the initial schema.

    Objects are dropped in reverse dependency order to satisfy foreign-key
    constraints.
    """
    # Drop indexes first (they depend on tables)
    op.execute("DROP INDEX IF EXISTS idx_audit_memory_id;")
    op.execute("DROP INDEX IF EXISTS idx_memories_user_id;")
    op.execute("DROP INDEX IF EXISTS idx_memories_tags;")
    op.execute("DROP INDEX IF EXISTS idx_memories_active;")
    op.execute("DROP INDEX IF EXISTS idx_memories_system_time;")
    op.execute("DROP INDEX IF EXISTS idx_memories_valid_time;")
    op.execute("DROP INDEX IF EXISTS idx_memories_decay_score;")
    op.execute("DROP INDEX IF EXISTS idx_memories_embedding;")

    # Drop tables (audit log first — it references memories)
    op.execute("DROP TABLE IF EXISTS memory_audit_log CASCADE;")
    op.execute("DROP TABLE IF EXISTS memories CASCADE;")

    # Drop custom types
    op.execute("DROP TYPE IF EXISTS memory_type;")

    # Drop extension (only if no other tables use it)
    op.execute("DROP EXTENSION IF EXISTS vector;")
