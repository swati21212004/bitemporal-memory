# Bitemporal AI Memory System — Build Plan

A production-grade persistent memory layer for AI assistants with semantic retrieval, temporal decay, bitemporal history, and behavioral guardrails.

---

## Technology Stack

| Layer             | Choice                                    | Rationale                                                      |
|:------------------|:------------------------------------------|:---------------------------------------------------------------|
| Database          | PostgreSQL 16 + pgvector                  | Vector similarity search + bitemporal range types              |
| Backend           | Python 3.11+ / FastAPI                    | Async-first, Pydantic validation, OpenAPI docs                 |
| ORM / DB          | SQLAlchemy 2.0 async + asyncpg            | Mature async PostgreSQL driver, pgvector support               |
| Migrations        | Alembic                                   | Industry standard for SQLAlchemy                               |
| Embeddings        | OpenAI text-embedding-3-small (1536d)     | Cost-effective, high quality; swappable via interface           |
| Scheduler         | APScheduler                               | Lightweight in-process cron for the decay job                  |
| Containerisation  | Docker Compose                            | PostgreSQL + pgvector + app in one command                     |
| Testing           | pytest + pytest-asyncio + httpx           | Async test client for FastAPI                                  |

---

## Project Structure

```
bitemporal-memory/
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
│       └── 001_initial_schema.py
├── sql/
│   └── schema.sql
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── database.py
│   ├── models/
│   │   ├── __init__.py
│   │   └── memory.py
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── memory.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── embedding.py
│   │   ├── memory_write.py
│   │   ├── memory_read.py
│   │   └── memory_forget.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── openai_tools.py
│   │   └── anthropic_tools.py
│   ├── jobs/
│   │   ├── __init__.py
│   │   └── decay.py
│   ├── guardrails/
│   │   ├── __init__.py
│   │   └── rules.py
│   └── api/
│       ├── __init__.py
│       └── routes.py
├── tests/
│   ├── conftest.py
│   ├── test_write.py
│   ├── test_read.py
│   ├── test_forget.py
│   └── test_guardrails.py
└── README.md
```

---

## Important Design Decision: Decay Score

PostgreSQL GENERATED ALWAYS AS requires IMMUTABLE expressions. Since decay depends
on now() (which is volatile), we CANNOT use a stored generated column. Instead:

  1. A regular decay_score FLOAT column with a B-tree index
  2. A background decay job (APScheduler, every 15 min) that recalculates scores
  3. On every read-access, we also touch last_accessed_at and recompute decay_score

This keeps indexes fresh with minimal application code — same end result.

---

## Defaults

- Retrieval weights: 0.6 semantic + 0.4 decay
- Memory types: episodic, semantic, procedural
- Contradiction threshold: 0.85 cosine similarity
- Multi-user support: yes (user_id field)

---

## Section 1-2: Schema (The Foundation)

Core tables:
  - memories: Main table with content, embedding (vector 1536), memory_type enum,
    importance (0-1), access_count, last_accessed_at, decay_score, bitemporal
    columns (created_at/superseded_at for system time, valid_from/valid_to for
    valid time), soft delete (is_deleted/deleted_at), and lineage tracking
    (supersedes_id, contradiction_of).
  - memory_audit_log: Immutable trail of every create/supersede/forget operation.

Key indexes:
  - HNSW on embedding for fast approximate nearest-neighbor vector search
  - B-tree on decay_score DESC (filtered to active memories)
  - B-tree on valid_from/valid_to for temporal queries
  - GIN on tags array for tag-based filtering
  - Composite on (user_id, memory_type, decay_score) for per-user fast paths

---

## Section 3: Write Path

  1. Embed the incoming content via OpenAI text-embedding-3-small
  2. Contradiction check: Query top-5 most similar existing memories
     - If cosine similarity > 0.95 → reject as duplicate
     - If cosine similarity > 0.85 but content diverges → return ContradictionDetected
       (DO NOT silently resolve — surface to user for explicit resolution)
     - If cosine similarity > 0.85 and content is an update → supersede old memory
       (set superseded_at = now(), insert new with supersedes_id)
  3. Insert new memory row with computed initial decay_score = importance
  4. Log to memory_audit_log with action = 'create'
  5. Return the created memory

---

## Section 4: Read Path (The Heart)

Hybrid retrieval query:

  WITH candidates AS (
      SELECT m.*,
          1 - (m.embedding <=> query_vector) AS semantic_score
      FROM memories m
      WHERE m.is_deleted = false
        AND m.superseded_at IS NULL
        AND m.valid_to IS NULL
        AND m.user_id = :user_id
      ORDER BY m.embedding <=> query_vector
      LIMIT 50
  )
  SELECT *,
      (0.6 * semantic_score) + (0.4 * decay_score) AS relevance_score
  FROM candidates
  ORDER BY relevance_score DESC
  LIMIT :top_k;

On every retrieval, update accessed rows:
  UPDATE memories
  SET access_count = access_count + 1, last_accessed_at = now()
  WHERE id = ANY(:ids);

Temporal query ("what did the system believe about me in March?"):
  WHERE created_at <= '2025-03-31'
    AND (superseded_at IS NULL OR superseded_at > '2025-03-01')
    AND valid_from <= '2025-03-31'
    AND (valid_to IS NULL OR valid_to > '2025-03-01')

System prompt integration: /memories/system-prompt endpoint returns formatted block
for LLM context injection.

---

## Section 5: Forget Path

NEVER HARD DELETE. Bitemporal history is the whole point.

  - Forget by ID: SET is_deleted = true, deleted_at = now(), valid_to = now()
  - Forget by semantic query: embed query, find matches, present for confirmation,
    then soft-delete confirmed ones
  - Forget by time range: soft-delete all memories with valid_from in range
  - Every operation logged to memory_audit_log

---

## Section 6: Tool Definitions

Three tools in both OpenAI function calling and Anthropic tool_use format:

  memory_write:
    params: content, memory_type, importance, tags, source
    desc: Store a new memory with contradiction detection

  memory_retrieve:
    params: query, top_k, memory_type, tags, time_range
    desc: Hybrid semantic+decay retrieval

  memory_forget:
    params: memory_id OR query, confirm
    desc: Soft-delete with user confirmation

---

## Section 7: Behavioral Guardrails

Deterministic guardrail engine (code-enforced, not just prompt-based):

  - Never silently resolve contradictions → return ContradictionDetected
  - Never hard delete → no DELETE FROM exists in the codebase
  - Importance bounds → Pydantic validator: 0.0 <= importance <= 1.0
  - PII gate → optional regex filter on write path, logs warnings
  - Source provenance → every memory must have source; inferred = lower importance
  - Staleness threshold → decay_score < 0.05 flagged for review
  - Rate limiting → max 100 writes/minute/user
  - Deduplication → cosine > 0.95 to same-type active memory = rejected

---

## Section 8: Decay Job

Background job (APScheduler, every 15 minutes):

  UPDATE memories
  SET decay_score = importance * (
      1.0 / (1.0 + LN(1.0 + EXTRACT(EPOCH FROM (now() - last_accessed_at)) / 86400.0))
  )
  WHERE is_deleted = false AND superseded_at IS NULL;

Decay curve properties:
  - Just accessed:  decay_score ~ importance
  - 1 day old:      decay_score ~ importance x 0.59
  - 7 days old:     decay_score ~ importance x 0.34
  - 30 days old:    decay_score ~ importance x 0.23

---

## API Endpoints

  POST   /memories                    → Write a new memory
  POST   /memories/search             → Hybrid semantic+decay search
  GET    /memories/{id}               → Get memory by ID
  GET    /memories/{id}/history       → Full bitemporal history
  POST   /memories/{id}/forget        → Soft-delete a memory
  POST   /memories/forget-by-query    → Semantic forget
  GET    /memories/temporal           → Temporal snapshot query
  POST   /memories/resolve-contradiction → Resolve detected contradiction
  GET    /memories/system-prompt      → Formatted memory block for LLM
  GET    /health                      → Health check

---

## Build Order

  Phase 1: Schema + Migration + Docker + Config     (8 files)
  Phase 2: Embedding service + Write path            (4 files)
  Phase 3: Read path + Hybrid query                  (2 files)
  Phase 4: API routes + System prompt                (2 files)
  Phase 5: Decay job                                 (2 files)
  Phase 6: Forget path + Audit log                   (2 files)
  Phase 7: Guardrails + Tools + Tests                (6 files)
  Phase 8: README + .gitignore + CI/CD + GitHub push

  Total: ~26 files

---

## What You Need

  - Git (you have it)
  - Docker Desktop (check tomorrow)
  - Python 3.11+ (check tomorrow)
  - OpenAI API key (for .env)

Everything else — I build automatically.
