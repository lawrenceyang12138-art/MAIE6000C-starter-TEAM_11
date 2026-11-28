# W13 PDF baseline — for D

Handoff from A, 2026-11-27. This is the PDF path the demo can rely on **now**,
verified on `develop` as it stands. Format work (TXT/Markdown/DOCX) is **not**
part of this handoff; it is wired after B, C and D land their final code.

## Commit

```
16251df8b1167a740d7f29863144a3859a65e4b9
Merge pull request #12 from lawrenceyang12138-art/feat/c-search-final-validation
```

`origin/develop` was at this commit when verification ran. No newer commit existed.

## Environment used

| Item | Value |
| --- | --- |
| Compose project | `team11-verify` (own volumes, network, containers) |
| API / frontend | http://127.0.0.1:8200 / http://127.0.0.1:3100 |
| PostgreSQL | 127.0.0.1:15433 |
| Corpus | `tests/fixtures/regression`, mounted read-only |
| Migration | `alembic_version = 20261119_0007`, single head |
| Model | cached PPLX, loaded from `./models`, no download |

## Verified run

| Step | Record |
| --- | --- |
| Authorize `corpus/regression` | 202; root `bf6e3001-e90e-46a1-b1ef-ee2e0b0ecd72`; **Job ID 1** |
| Scan | job 1 `completed`; 13 files → 12 readable, 1 unsupported |
| Search `maintenance windows` (keyword) | `doc03.pdf`, page **1**, score 1.0, `effective_mode=keyword` |
| Evidence | chunk `824d9556-8b88-4c4b-9779-e7edb16e116d`, page 1, SHA-256 `0385f56f…`, text contains the term |
| Page cross-check | PyMuPDF on `group-a/doc03.pdf` page 1 contains the same phrase — page number and text agree |
| Whole corpus (with abnormal) | root `08728db0-…`; 16 files → 12 readable, 4 unsupported with `corrupt`, `encrypted`, `no_text_layer`, `unsupported_format`; bad files never block good ones |
| Rescan | versions 29 → 29, extract jobs 29 → 29, chunks 60 → 60 |
| Restart | `restart api worker`; same chunk id, same content SHA, same top search hit |

Status note for the UI: readable versions report `enriched` once the local model
publishes vectors (contract 8). Before the model is ready the same files are
`basic_ready`. Both mean "readable"; the demo should not treat `enriched` as an
error.

## Reproduce

```bash
git checkout --detach 16251df
API_HOST_PORT=8200 FRONTEND_HOST_PORT=3100 POSTGRES_HOST_PORT=15433 \
  docker compose -p team11-verify up -d
curl -s localhost:8200/health/ready                     # 200

curl -s -X POST localhost:8200/roots -H 'content-type: application/json' \
  -d '{"mount_id":"corpus","relative_path":"regression"}'
curl -s localhost:8200/jobs/1                            # completed
curl -s "localhost:8200/files?root_id=<root_id>"

curl -s -X POST localhost:8200/search -H 'content-type: application/json' \
  -d '{"query":"maintenance windows","mode":"keyword"}'
curl -s localhost:8200/evidence/<chunk_id>
```

## For D

- Expected on screen: 16 files, 12 readable, 4 unsupported with the four reason
  codes above; search `maintenance windows` lands on `doc03.pdf` page 1.
- The local-folder button still needs `python scripts/local_folders.py --serve`
  in the operator terminal; this is a demo-time prerequisite, not a defect.
- If the UI must show "port" numbers, nothing changed since W7.

## Scope

No team database was migrated or rewritten; the verification project owns its
volume. This handoff does not include the optional formats: those switches are
wired after the other roles' final code, and will be delivered with their own
matrix and rollback notes.
