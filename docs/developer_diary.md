# Bitemporal Memory System — Developer Diary

Welcome to the development diary. This document tracks the design decisions, mathematical models, and implementation details of the Bitemporal Memory System from inception to completion.

## Technical Decisions: Database Selection

We evaluated multiple storage backends. While SQLite is lightweight for local testing, PostgreSQL 16 was selected as the core engine due to native `pgvector` support, mature connection pooling, and rich index types which are essential for high-performance vector search in production AI systems.

