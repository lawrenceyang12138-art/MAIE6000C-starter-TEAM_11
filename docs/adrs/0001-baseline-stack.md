# ADR 0001 — Baseline Starter Stack

## Status

Accepted

## Decision

The starter template uses:

- FastAPI for HTTP services
- PostgreSQL for relational persistence
- SQLAlchemy + Alembic for ORM and migrations
- a separate worker process for async job execution
- a separate internal AI service for service-boundary demonstration
- Docker Compose for reproducible local startup

## Rationale

This stack supports the core learning goals of the course without requiring paid services or advanced infrastructure.

It gives students a concrete baseline for:

- database-backed workflows
- networked service design
- background processing
- local reproducibility
- operational reasoning

## Consequences

This starter favors clarity and teachability over completeness.

Teams are expected to extend or replace parts of the starter while preserving the course engineering contract.
