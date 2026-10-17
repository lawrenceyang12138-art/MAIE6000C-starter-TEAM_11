# File Management Assistant

MAIE 6000C Team 11

File Management Assistant is a proposed local-first tool for people who accumulate personal and project files across folders. Starting from a selected, authorized folder, it will support keyword and semantic retrieval, source-linked evidence, and a graph connecting files with the people, projects, and topics they mention. Original files remain read-only for the core release; moving, renaming, and undoing file operations are stretch goals, not R1 acceptance gates.

This repository is the MAIE 6000C: **Engineering AI Products: From Prototype to Production** Team 11 project. It now includes read-only folder authorization, document indexing and parsing components, and bilingual keyword/semantic search with source evidence. Search implementation and verification details are in the [search plan](docs/search-plan.md) and [integration handoff](docs/search-integration-handoff.md).

## Documentation

- [Detailed architecture](docs/architecture.md): workflow, service boundaries, persistence, state transitions, AI processing, failure behavior, and design evidence.
- [Search implementation](docs/search-plan.md): keyword and semantic retrieval, model configuration, and verification.
- [Search integration handoff](docs/search-integration-handoff.md): shared contracts and remaining integration notes.
- [Week 4 proposal and project plan](submissions/week04/README.md): milestone summary, scope priorities, risks, artifact index, and AI Use Statement.
- [Starter operations notes](docs/operations.md): existing service health, metrics, and development commands. These describe the baseline, not the proposed product.

## Current repository status

The repository has advanced beyond the Week 4 documentation baseline. The API includes case and authorized-root workflows plus `/search` for indexed source chunks. Search supports keyword retrieval and configured semantic/hybrid retrieval with keyword fallback when embeddings are unavailable. The end-to-end workflow and graph still depend on integration across the team branches.

The existing course starter demonstrates case creation through FastAPI, PostgreSQL persistence, a queued background job, an internal AI-service call, and worker result write-back. It includes SQLAlchemy/Alembic, Docker Compose, health endpoints, structured logging, metrics, and test scaffolding. The architecture document distinguishes these existing capabilities from the proposed File Management Assistant.

## Run the starter baseline

Prerequisites: Docker with Compose; Python 3.11 for local tests. On Windows PowerShell, create the local environment file only if `.env` does not already exist:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
docker compose up --build
```

On a POSIX shell, use `test -f .env || cp .env.example .env` before starting Compose. Do not overwrite an existing local configuration or commit secrets.

Default endpoints (host ports can be changed in `.env`):

- [API documentation](http://localhost:8000/docs)
- [Starter AI-service documentation](http://localhost:8100/docs)
- [Prometheus](http://localhost:9090), when started with `docker compose --profile observability up --build`

The starter workflow creates a case with `POST /cases`, then retrieves it with `GET /cases/{id}` to observe worker processing. Folder authorization uses `POST /roots`, and indexed source chunks can be queried with `POST /search`. Use only public, synthetic, anonymized, or instructor-approved demo data.

The current starter's published ports are not loopback-restricted. Do not expose it to an untrusted network; the proposed product's local-only deployment hardening is documented in the architecture, not implemented by this checkpoint.

## Development and verification

Install development dependencies and run the starter unit/integration tests:

```powershell
python -m pip install -e ".[dev]"
python -m pytest -q tests/unit tests/integration
```

Against an already running stack, run the starter smoke test in PowerShell:

```powershell
$env:SMOKE_BASE_URL = "http://localhost:8000"
python -m pytest tests/smoke -q
```

The POSIX equivalent is `SMOKE_BASE_URL=http://localhost:8000 python -m pytest tests/smoke -q`. These tests exercise the existing case workflow; they do not establish product acceptance or PostgreSQL restart persistence.

Useful baseline commands:

```powershell
docker compose run --rm api alembic upgrade head
docker compose run --rm api python scripts/seed_demo_data.py
docker compose down --remove-orphans
```

Normal shutdown preserves the named database volume. Volume-reset commands in the operations notes remove local database state; do not use them when checking restart persistence.
