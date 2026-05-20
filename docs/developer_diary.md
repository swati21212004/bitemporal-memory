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

