# Starter Architecture

## Components

- **API service**: accepts requests, validates input, persists workflow state
- **PostgreSQL**: stores cases and jobs
- **Worker**: polls pending jobs and processes them outside the request cycle
- **AI service**: receives internal triage requests and returns a label, summary, and confidence

## Baseline flow

1. client sends `POST /cases`
2. API writes a case row
3. API writes a pending job row
4. worker claims the pending job
5. worker calls the internal AI service
6. worker writes the triage result back to the case
7. API exposes the updated case state

## Why this starter exists

This starter is intentionally small.

Its purpose is to demonstrate the engineering shape of the course contract:

- persistence
- API boundaries
- async work
- service-to-service communication
- testing
- observability
- reproducible deployment

## Current limitations

- single polling worker
- simple heuristic AI service placeholder
- no authentication or authorization
- no retry strategy beyond basic failure recording
- minimal domain model
