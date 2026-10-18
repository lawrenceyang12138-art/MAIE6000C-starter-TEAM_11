# Team 11 · File Ownership Map (owner-map, 2026-10-16)

Convention: shared models / schema / migrations and API assembly are modified by A only; B and C write processors and tests in their own directories; contract changes are confirmed jointly before landing, to avoid simultaneous edits to the same file; nothing is merged before tests and static checks pass.

## Branch ownership

| Branch | Owner | Contents |
| --- | --- | --- |
| `main` | All (merged by D) | Stays at the starter; D performs the merges |
| `w7-scan-dispatch` | A | Authorization / scan / worker dispatch / read-only mounts / scan tests |
| `w7-parsing` | B | Parsing / chunking / evidence / relations / reviews |
| `week04-architecture-proposal` | Documentation baseline | Product direction and technical spec (`docs/architecture.md` is the authority) |

## Path ownership

| Path | Owner | Notes |
| --- | --- | --- |
| `services/scan/` | A | Scan traversal, path resolution |
| `services/worker/app/main.py` | A | Job dispatch |
| `services/api/app/main.py` | A | Route assembly (B built the `/roots` skeleton; A integrates only) |
| `services/common/` (models / schemas / config / db) | A | Schema decisions and configuration; B / C submit field and DDL intent, never edit shared files |
| `alembic/` | A | Migrations land through A only |
| `compose.yaml` / `Dockerfile` / `.env.example` | A | Deployment and mount configuration |
| `docs/architecture.md` / `docs/operations.md` | A | W07 documentation sync |
| `contracts.md` | A | Interface contracts |
| `services/parsing/` | B | Parsing / chunking / evidence / relations / reviews; A calls but never edits |
| `tests/fixtures/` | B (rehearsal) / D (official) | Corpus and fixtures |
| `tests/unit/test_parsing_*`, `tests/integration/test_extraction_regression.py` | B | Parsing-side tests |
| `tests/unit/test_scan_handler.py` | A | Scan-side tests |
| `submissions/week07/B-*` | B | B's sections / notes / evidence |
| `submissions/week07/A-*` | A | A's sections / notes / evidence |
| Search / vector processor | C | DDL intent is handed to A; the search contract is completed once C's endpoints exist |
| Frontend | D | Authorization / progress / results / evidence / relations / review pages |
| `evidence/` | Per module | Acceptance summaries collected per module |
