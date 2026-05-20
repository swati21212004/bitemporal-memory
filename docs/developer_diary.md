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

