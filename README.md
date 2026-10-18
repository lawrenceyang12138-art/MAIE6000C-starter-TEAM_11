# File Management Assistant

MAIE 6000C Team 11

File Management Assistant is a proposed local-first tool for people who accumulate personal and project files across folders. Starting from a selected, authorized folder, it will support keyword and semantic retrieval, source-linked evidence, and a graph connecting files with the people, projects, and topics they mention. Original files remain read-only for the core release; moving, renaming, and undoing file operations are stretch goals, not R1 acceptance gates.

## Documentation

- [Detailed architecture](docs/architecture.md): workflow, service boundaries, persistence, state transitions, AI processing, failure behavior, and design evidence.
- [Week 4 proposal and project plan](submissions/week04/README.md): milestone summary, scope priorities, risks, artifact index, and AI Use Statement.
- [Starter operations notes](docs/operations.md): existing service health, metrics, and development commands. These describe the baseline, not the proposed product.

## Current repository status

This Week 4 change is documentation only. Folder selection, document indexing, search, the graph, and human review are **not implemented yet**.

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

The baseline workflow is to create a case with `POST /cases`, then retrieve it with `GET /cases/{id}` to observe worker processing. These are starter routes, not document-search endpoints. Use only public, synthetic, anonymized, or instructor-approved demo data.

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

## D frontend

The D demo frontend is available at `http://localhost:3000/select`. It defaults
to API mode and uses the same-origin `/api` proxy. API errors remain explicit;
the frontend never silently falls back to demo data. Use
`FRONTEND_DATA_MODE=mock` before rebuilding for an explicitly labeled synthetic
demonstration. Existing `.env` settings take precedence; do not overwrite them
just to change modes. See [D's 16 October handoff](submissions/week07/ui-progress.md)
and the [consumer contract](docs/frontend-integration-contract.md) for verified
work and outstanding real-integration requirements.

The 16 October D verification includes a successful production build, 35 Node
contract tests, 9 Vitest adapter/helper tests and 8 watermarked browser fixture
scenarios. These do not establish live API/DB/Worker integration. See the
[evidence index](submissions/week07/evidence/1016-D/README.md).
