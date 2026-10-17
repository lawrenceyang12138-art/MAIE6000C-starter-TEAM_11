# W7 Release Manifest (release candidate)

Status: release candidate for the M1 review. The final recording and
second-computer installation record still need to be added before the 24
October presentation.

## Source

- Repository: `https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11`
- Branch: `w7-integration-bootstrap`
- Code commit: `7b0b6ef665af79dee1cbb20a78058be7c5dc313b`
- Materials commit: `636170e` (this manifest and the matching deck/report set)
- Alembic head: `a1b2c3d4e5f6`

## Runtime

- API: `http://127.0.0.1:8000`
- Frontend: `http://127.0.0.1:3000`
- AI service: `http://127.0.0.1:8100`
- PostgreSQL: `pgvector/pgvector:pg16`, host port 5432 in the test project
- Corpus mount: `fixtures/demo-corpus`, read-only at `/source/corpus`

## Image digests observed

| Service | Image ID |
| --- | --- |
| API | `sha256:2607759bebf21eed0bdac2b7a0db062d1470b56e3a2ecaf86255ac00b51ca75e` |
| Worker | `sha256:8685b9e4bab4ea7301af50991b58c6299b3dc21d4fc16c1190d0ffa8eed8ef28` |
| Frontend | `sha256:40d7920178b0072376b186135f74a7e265073df98c7c7ca876e63d1ebaa00a05` |
| AI | `sha256:6bd11346b15b32ccfdf8188d3f35f60a6a4c76bfecd1de363605fa8cc141c257` |
| Database | `sha256:f40e48eca747184a758d8f04b465186c04f1c9d7c2bee3935cc38cebdaf52326` |

## Artifact hashes

| Artifact | SHA-256 |
| --- | --- |
| `W07_Team11.pptx` | `5904e5331357b74705555f5228703f7276113e7f145dc4f0f6b9722defaddc46` |
| `W07_Team11.pdf` | `9347ecdb3cfa74966888902c789797056afaf0ac25e7c33295d32e5bf322d890` |
| `report.md` | `b0d8ecdccdff70599b1e20a2c35f7c79221c757ad93d2ebdb089c45b6cdd0d14` |
| `README.md` | `8ab9efcc64e875bc8b764551b068277bad2bdfdaa0aa0a40cd90decbbc406066` |

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
