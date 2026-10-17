# W7 Release Manifest (release candidate)

Status: release candidate for the M1 review. The final recording and
second-computer installation record still need to be added before the 24
October presentation.

## Source

- Repository: `https://github.com/lawrenceyang12138-art/MAIE6000C-starter-TEAM_11`
- Branch: `w7-integration-bootstrap`
- Code commit: `ed83f64` (semantic intent + bounded worker reliability)
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
| `W07_Team11.pptx` | `3410a7a4dbc65b877478682b76256e8d7d90a84e0b0aa41bdcc2cb6922947eb9` |
| `W07_Team11.pdf` | `cedda15282d141d03df2e735aee1149b8e86637976ca3f8f83b05a59fee1bfe1` |
| `report.md` | `1ec0d90b5d851fa1d6291a21d58e1359dea949f69deb6c6336f688fab5711b44` |
| `README.md` | `281f373413da5c8b105e60688e8c4ccd445616edc2c45fa92b089f6876177b37` |

## Model cache

The pinned local E5 model is prepared at `models/multilingual-e5-small`
(about 486MB, revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`, six files plus checksum
manifest). It is intentionally excluded from Git. Copy this directory into
the offline release bundle and build the AI image with
`INSTALL_EMBEDDINGS=1`. The real verification is **20 embedded chunks, S01–S05
Top-3 5/5 and evidence 5/5**; it is a synthetic smoke test, not a general
semantic benchmark.

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
