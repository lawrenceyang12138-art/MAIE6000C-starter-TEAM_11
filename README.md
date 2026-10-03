# MAIE 6000C Starter Template

This repository is the starter template for MAIE 6000C: **Engineering AI Products: From Prototype to Production**.

It is intentionally small, but it already demonstrates the core engineering shape expected in the course:

- a public-facing API service
- a separate internal AI service
- a worker process
- a PostgreSQL database
- Alembic migrations
- Docker Compose deployment
- unit, integration, and smoke testing support
- structured logging
- health checks
- basic metrics

## Purpose of this repository

This repository is **not** meant to be a feature-complete product.

Its purpose is to provide a working baseline that teams will extend into their semester project while preserving the course’s engineering contract.

## Course engineering contract

Every passing team project built from this template must ultimately include:

- a meaningful relational database layer
- a service or API layer
- a worker or async path outside the immediate request cycle
- an AI-enabled function integrated into the workflow
- reproducible local deployment
- tests or credible verification
- documentation
- structured logs
- health checks
- basic observability

## Baseline workflow in the starter

The starter demonstrates a simple end-to-end flow:

1. create a case through the API
2. store that case in PostgreSQL
3. create a background job
4. let the worker claim and process the job
5. call the internal AI service over HTTP
6. persist the result
7. retrieve updated state through the API

This gives you a starting point for:

- persistence
- inter-service communication
- worker-based execution
- deployment
- testing
- observability

## Repository structure

Typical structure:

```text
.
├─ .github/
├─ alembic/
├─ docs/
├─ observability/
├─ scripts/
├─ services/
│  └─ api/
├─ submissions/
│  ├─ week04/
│  ├─ week07/
│  └─ week13/
├─ tests/
├─ .env.example
├─ compose.yaml
├─ Makefile
├─ pyproject.toml
└─ README.md
```

## Core services

### API service

The API service is the main entry point for requests and exposes routes for core system actions.

### AI service

The AI service is a separate internal service used to demonstrate service-to-service communication for an AI-enabled function.

### Worker

The worker processes jobs outside the immediate request cycle.

### Database

PostgreSQL is used as the relational persistence layer.

## Quick start

### 1. Copy environment file

```bash
cp .env.example .env
```

### 2. Start the stack

```bash
docker compose up --build
```

### 3. Optional observability profile

```bash
docker compose --profile observability up --build
```

### 4. Open the relevant endpoints

- API docs: `http://localhost:8000/docs`
- AI service docs: `http://localhost:8100/docs`
- Prometheus: `http://localhost:9090` if the observability profile is enabled

## Typical development commands

### Start the stack

```bash
docker compose up --build
```

### Stop the stack

```bash
docker compose down --remove-orphans
```

### Stop and remove volumes

```bash
docker compose down -v --remove-orphans
```

### Run tests

```bash
pytest -q
```

### Run smoke tests against a running stack

```bash
SMOKE_BASE_URL=http://localhost:8000 pytest tests/smoke -q
```

### Run migrations

```bash
docker compose run --rm api alembic upgrade head
```

### Seed demo data

```bash
docker compose run --rm api python scripts/seed_demo_data.py
```

## What teams are expected to change

Teams are expected to extend or replace:

- the domain model
- routes and workflows
- worker job types
- AI-enabled logic
- tests
- documentation
- observability depth

Teams are not expected to replace the course operating model or ignore the required repository structure.

## Required living documents for team repositories

By the time this template becomes a semester team project repo, it should maintain:

- `README.md`
- `docs/architecture.md`
- `docs/operations.md`
- `docs/adrs/`
- `submissions/week04/`
- `submissions/week07/`
- `submissions/week13/`

## Required milestone tags for team projects

When this repo is used as a semester project repository, the required milestone tags are:

- `w04-proposal`
- `w07-midterm`
- `w13-final`

## Branch conventions

Recommended branch prefixes:

- `feature/...`
- `fix/...`
- `docs/...`
- `submission/...`

Default branch:

- `main`

## Testing expectations

A strong project should maintain some combination of:

- unit tests
- integration tests
- smoke tests
- credible end-to-end verification

The exact test mix may vary, but important behavior must be checkable and explainable.

## Observability expectations

At minimum, projects should support:

- structured logs
- health checks
- basic metrics or equivalent observability signals

Do not wait until the end of the semester to add operational visibility.

## Data and privacy expectations

Projects in this course must use only:

- public data
- synthetic data
- anonymized data
- instructor-approved sources

Do not commit secrets to the repository.

Do not log sensitive or unnecessary data carelessly.

## AI use reminder

If you use generative AI tools during development, you must remain able to explain your work and include the required AI Use Statement in major submissions.

The AI-enabled feature in your system is separate from optional AI tool use during development.

## Suggested first steps for teams

When beginning your project, do the following early:

- confirm the repo boots from a clean clone
- understand the current workflow end to end
- choose a narrow core workflow
- identify your main persistent entities
- identify your worker path
- decide where the AI-enabled function belongs
- update documentation as soon as design changes

## Final reminder

This course rewards engineering maturity.

A smaller, reliable, well-documented system built from this template is stronger than a large but fragile system built on rushed changes.
