-- ============================================================================
-- Bitemporal AI Memory System — Core Schema
-- PostgreSQL 16 + pgvector
-- ============================================================================

-- Enable vector extension
CREATE EXTENSION IF NOT EXISTS vector;

-- ── Memory type enum ─────────────────────────────────────────────────────────
CREATE TYPE memory_type AS ENUM ('episodic', 'semantic', 'procedural');

-- ── Core memories table ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memories (
    -- Identity
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id           TEXT NOT NULL DEFAULT 'default',

    -- Content
    content           TEXT NOT NULL,
    embedding         vector(1536) NOT NULL,
    memory_type       memory_type NOT NULL DEFAULT 'semantic',
    tags              TEXT[] DEFAULT '{}',
    source            TEXT NOT NULL DEFAULT 'conversation',
    metadata          JSONB DEFAULT '{}',

    -- Importance & Decay
    importance        FLOAT NOT NULL DEFAULT 0.5
                      CHECK (importance >= 0.0 AND importance <= 1.0),
    access_count      INTEGER NOT NULL DEFAULT 0,
    last_accessed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    decay_score       FLOAT NOT NULL DEFAULT 0.5,

    -- Bitemporal: System Time (when the DB recorded it)
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    superseded_at     TIMESTAMPTZ,

    -- Bitemporal: Valid Time (when the fact was true in reality)
    valid_from        TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to          TIMESTAMPTZ,

    -- Soft delete (never hard delete)
    is_deleted        BOOLEAN NOT NULL DEFAULT false,
    deleted_at        TIMESTAMPTZ,

    -- Lineage
    supersedes_id     UUID REFERENCES memories(id),
    contradiction_of  UUID REFERENCES memories(id)
);

-- ── Audit log ────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS memory_audit_log (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    memory_id     UUID NOT NULL REFERENCES memories(id),
    user_id       TEXT NOT NULL DEFAULT 'default',
    action        TEXT NOT NULL,
    reason        TEXT,
    old_content   TEXT,
    new_content   TEXT,
    performed_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Indexes ──────────────────────────────────────────────────────────────────

-- Vector similarity (HNSW for fast approximate nearest-neighbor)
CREATE INDEX IF NOT EXISTS idx_memories_embedding
    ON memories USING hnsw (embedding vector_cosine_ops);

-- Decay score ranking for active memories
CREATE INDEX IF NOT EXISTS idx_memories_decay_score
    ON memories (decay_score DESC)
    WHERE is_deleted = false AND superseded_at IS NULL;

-- Bitemporal query indexes
CREATE INDEX IF NOT EXISTS idx_memories_valid_time
    ON memories (valid_from, valid_to)
    WHERE is_deleted = false;

CREATE INDEX IF NOT EXISTS idx_memories_system_time
    ON memories (created_at, superseded_at);

-- Active memories fast path (per user)
CREATE INDEX IF NOT EXISTS idx_memories_active
    ON memories (user_id, memory_type, decay_score DESC)
    WHERE is_deleted = false AND superseded_at IS NULL AND valid_to IS NULL;

-- Tag-based filtering (GIN for array containment)
CREATE INDEX IF NOT EXISTS idx_memories_tags
    ON memories USING gin (tags);

-- User-scoped lookups
CREATE INDEX IF NOT EXISTS idx_memories_user_id
    ON memories (user_id)
    WHERE is_deleted = false;

-- Audit log lookup by memory
CREATE INDEX IF NOT EXISTS idx_audit_memory_id
    ON memory_audit_log (memory_id);
