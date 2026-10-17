# W7 Release Manifest (release candidate)

Status: release candidate for the M1 review. The final recording and
second-computer installation record still need to be added before the 24
October presentation.

## Source

- Repository: `https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11`
- Branch: `w7-integration-bootstrap`
- Commit: `045be531b67c8aeacbdb17b4065a6beb9822dfb7`
- Alembic head: `7f3a1b2c4d5e`

## Runtime

- API: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:3000`
- AI service: `http://127.0.0.1:8100`
- PostgreSQL: `pgvector/pgvector:pg16`, host port 5432 in the test project
- Corpus mount: `fixtures/demo-corpus`, read-only at `/source/corpus`

## Image digests observed

| Service | Image ID |
| --- | --- |
| API | `sha256:0793c303c408c208e1deb9cd91c717de85cbef034c81e165ca7fe47b7df12308` |
| Worker | `sha256:40866084ebe305bb9b2f519ed33a855510e7e24bbad85a5cce95e2e0451d9c31` |
| Frontend | `sha256:0bb26f68f6ef45eb093bfd1dab3085e0e28e43e5fee4f61d84bd946cb00101a0` |
| AI | `sha256:6c632009d6b43ac5b746e95c814fc098fc6edd597362820127b4a0690a4cf2fe` |
| Database | `sha256:f40e48eca747184a758d8f04b465186c04f1c9d7c2bee3935cc38cebdaf52326` |

## Artifact hashes

| Artifact | SHA-256 |
| --- | --- |
| `W07_Team11.pptx` | `47c065a8dc61467c83a15f40687b81c8763be8fab4f8e69af5a1b2885fd26f9a` |
| `W07_Team11.pdf` | `6282a8a8a662a65ddaa516c6f0531bc711b4ba0ace55a7a731a882f8c10602a8` |
| `report.md` | `a503764d08d4c6c458fd88d1872084194b98a6be614f7f44271f7b4b02c53f7d` |
| `README.md` | `369c4a0e2662e57a015718d9f8fcadeba89e7700e89d3c237a3d78b94a0f70be` |

## Model cache

The pinned local E5 model is **not present** in this checkout. The semantic
path therefore reports a keyword-only degradation. Do not claim semantic
quality from this release candidate. The intended path is
`models/multilingual-e5-small` with the manifest described in
`services/search/embeddings.py`.

## Start and migration

```text
docker compose -p team11_c_test up -d --build db ai api worker frontend
docker compose -p team11_c_test exec api alembic upgrade head
```

The API container runs the migration on startup in the Compose definition.
The browser acceptance record is
`submissions/week07/evidence/m1-browser-2026-10-17.md`.

## Pending before final freeze

- Add `demo-backup.mp4` (3–4 minutes, same commit and corpus).
- Run the second-computer install and record the result.
- Freeze the final PPT/PDF and record the matching hashes after the recording.
- Obtain A/C/D review of their draft sections and AI statements.
