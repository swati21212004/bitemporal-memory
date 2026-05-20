# Bitemporal Memory System — Developer Diary

Welcome to the development diary. This document tracks the design decisions, mathematical models, and implementation details of the Bitemporal Memory System from inception to completion.

## Technical Decisions: Database Selection

We evaluated multiple storage backends. While SQLite is lightweight for local testing, PostgreSQL 16 was selected as the core engine due to native `pgvector` support, mature connection pooling, and rich index types which are essential for high-performance vector search in production AI systems.

## Vector Search with pgvector

Traditional databases struggle with high-dimensional vector representations. By using `pgvector`, we can store OpenAI's 1536-dimensional embeddings directly in the `memories` table and execute similarity queries in native SQL, drastically reducing round-trip latency.

## Connection Pooling Configurations

For high concurrency, SQLAlchemy's async engine was configured with a base `pool_size` of 10 and a `max_overflow` of 20. A `pool_pre_ping=True` check was added to automatically recycle stale database connections and prevent connection dropouts.

## Async Session Lifecycle Management

We implemented a FastAPI dependency (`get_session`) that yields an async SQLAlchemy session. It ensures that every transaction is either successfully committed or rolled back automatically in case of errors, preventing open connection leaks.

## Bitemporality Concept

Bitemporal databases track two axes of time:
1. **System Time** (`created_at` / `superseded_at`): The time the database recorded the statement.
2. **Valid Time** (`valid_from` / `valid_to`): The time the fact was true in reality.
This allows the assistant to reconstruct historical memory states at any point in time.

## Vector Indexing: HNSW vs IVFFlat

We chose Hierarchical Navigable Small World (HNSW) indexes over IVFFlat. HNSW provides faster query execution speeds and higher recall accuracy for 1536-dimensional vectors, without needing a training phase.

## Database Index Optimizations

We created a composite index on active memories: `(memory_type, decay_score DESC) WHERE is_deleted = false AND superseded_at IS NULL AND valid_to IS NULL`. This allows the API to serve typical retrieval paths in sub-millisecond times.

## Indexing Tags with GIN

Memory tags are represented as a PostgreSQL text array (`TEXT[]`). We created a Generalized Inverted Index (GIN) on the tags column to allow sub-millisecond lookups for subset intersection queries (`tags @> :filter_tags`).

## Embedding Abstraction

We built an abstract `EmbeddingService` interface. This allows developers to swap the default OpenAI provider for local alternatives (like Ollama or sentence-transformers) without changing a single line of business logic.

## OpenAI Embedding Provider

The default implementation utilizes `text-embedding-3-small` due to its high accuracy, compact size, and low token cost. It maps raw conversational text to a normalized 1536-dimensional floating point array.

## Batch Embedding Operations

For bulk imports or large-scale document parsing, the embedding service supports batching multiple text payloads into a single HTTP API call to OpenAI, minimizing connection overhead.

## Contradiction Math

To prevent the AI from accepting conflicting statements (e.g. 'I hate coffee' vs 'I love coffee'), the write path runs a cosine similarity scan. Similarity is calculated as the dot product of normalized embedding vectors.

## Deduplication Rules

If a new memory's cosine similarity to an active memory of the same type exceeds `0.95`, it is rejected as a duplicate. This saves storage space and prevents vector clutter.

## Manual Contradiction Resolution

When similarity is above `0.85` but meanings diverge, the system blocks the write and returns `409 Conflict`. The client must explicitly resolve it by either superseding the old memory or choosing to keep both.

## Pydantic Schemas

We designed highly validated Pydantic v2 schemas. They enforce strict validation rules on the incoming request (`MemoryCreate`) and format outbound responses (`MemoryResponse`) with clean datetime serializations.

## Hybrid Retrieval scoring

Instead of purely returning the closest vector matches, we implement a hybrid relevance score:
`Relevance = 0.6 * SemanticScore + 0.4 * DecayScore`.
This ensures that highly relevant, fresh facts are surfaced over distant historical ones.

## Access Tracking

Every time a memory is returned during retrieval, the system records the access by incrementing `access_count` and setting `last_accessed_at = now()`. This temporarily boosts the memory's decay score back to its original importance.

## Time Travel Queries

We designed native SQL patterns to query the state of memory as it existed in the past. By querying with timestamps, the system can reconstruct the precise set of facts the AI believed at any historical point.

## Logarithmic Decay Formula

Memories fade according to the logarithmic formula:
`decay_score = importance * (1.0 / (1.0 + ln(1.0 + age_in_days)))`.
This models human cognitive retention, where details fade rapidly initially and then level off.

## Background Scheduler

To ensure scores stay fresh without bloating read paths, an in-process APScheduler background job executes a bulk update query in PostgreSQL every 15 minutes, recalculating scores based on passage of time.

## Keeping Indexes Fresh

Since the decay job runs every 15 minutes, the database index on `decay_score` is continuously updated. This ensures that the candidate pool for hybrid retrievals remains extremely accurate and indexed.

## Soft-Delete Implementation

To preserve historical integrity for auditability, the memory system never executes physical SQL `DELETE` statements. Forgetting a memory simply flags `is_deleted = true` and sets `deleted_at = now()`.

## Immutable Audit Logs

Every single write, version supersede, and soft-delete operation is logged to the `memory_audit_log` table. This provides a complete, tamper-proof history of memory lifecycle changes.

## Time-Range Deletion

Users can request to forget a specific window of time (e.g. 'forget what I said yesterday'). The system targets memories where `valid_from` falls inside that range and soft-deletes them cleanly.

## Semantic Forget Operations

If a user says 'forget my preferences about food', the system embeds the query, retrieves matching memories, presents them for confirmation, and then soft-deletes the confirmed records.

## LLM Integration: OpenAI Tools

We wrote native JSON tool schemas for OpenAI function calling. These allow GPT-4 series models to automatically parse user intents into `memory_write`, `memory_retrieve`, or `memory_forget` tool calls.

## LLM Integration: Anthropic Tools

In addition to OpenAI, we created full definitions compatible with Anthropic's tool_use parameter format, making this memory system fully multi-model capable.

## Hardened Code Guardrails

We believe security should be enforced in compile-time/run-time code, not just prompt instructions. All bounds, types, PII rules, and rate limits are hard-coded into our core guardrail middleware.

## PII Shield: Email and SSN

We implemented rigorous regex matching to detect and quarantine sensitive information like standard emails and US Social Security Numbers (`###-##-####`) before they enter the vector database.

## PII Shield: Credit Cards and Phones

Additional regex rules capture Visa/Mastercard configurations and complex phone numbers (handling international codes, dashes, and parenthesized area codes like `(555) 123-4567`).

## Write Rate Limiting

To prevent denial of service or loop-flooding, we built an in-memory sliding window rate limiter that restricts writes to a maximum of 100 per minute per user session.

## Memory Type Constraints

We enforce that every memory falls strictly into one of three pre-defined categories: `episodic`, `semantic`, or `procedural`, rejecting arbitrary strings at the API layer.

## Importance Validation

Pydantic validators enforce that all memory importance scores are bounded strictly between `0.0` (trivial) and `1.0` (critical), preventing out-of-bounds math calculation errors.

## Source Provenance tracking

All stored memories must explicitly declare their origin. Memories marked as `inferred` by the LLM are automatically assigned lower default importance than those explicitly stated by the user.

## Flagging Stale Memories

Memories with a calculated decay score below `0.05` are automatically flagged in the retrieval payload, prompting the LLM agent to ask the user if the fact is still correct or needs updating.

## FastAPI Routing Architecture

The REST API is structured cleanly with separate routers. Main endpoints include `/memories`, `/memories/search`, `/memories/{id}/history`, and `/memories/system-prompt`.

## System Prompt Injection Layout

We built a formatter that serializes retrieved memories into a clean, markdown-friendly block. This is designed to be directly appended to the LLM system prompt context.

## System Health Monitoring

A simple `/health` endpoint executes a dummy SQL query (`SELECT 1`) to verify that the API server is healthy and the database connection pool is active.

## High-Coverage Testing

We built a robust test suite of 94 tests using `pytest` and `pytest-asyncio`, covering schema constraints, guardrail logic, decay curves, and temporal query responses.

## Mock Embedding Architecture

To ensure tests run fast and securely without requiring an internet connection or incurring OpenAI token costs, `conftest.py` patches the embedding layer with deterministic mock arrays.

## Continuous Integration Pipeline

We configured a GitHub Actions CI workflow (`.github/workflows/ci.yml`) that builds the project, runs linting rules, and executes the entire 94-test suite on every single commit.

