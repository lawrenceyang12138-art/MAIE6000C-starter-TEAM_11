# API contract: what exists, what is called, what is missing

Owner of this draft: B. Owner of the decision: A (routes, shared model,
assembly). Written on 2026-10-17 from the four remote branches, not from any
plan document.

## Why this exists

Each branch is healthy alone. The merge conflicts are the visible problem, but
they are not the biggest one: **the front end calls endpoints that no branch
serves**, and that would survive a conflict-free merge.

Evidence:

- `frontend/src/api/http-adapter.js` on `Role_D` calls `/mounts`, `/mounts/{id}`,
  `/roots`, `/roots/{id}`, `/files?root_id=...`,
  `/files/{id}/evidence?version_id=...` and `/jobs/{id}`
- `services/api/app/main.py` on `w7-parsing` serves `/roots` and `/roots/{id}`
  (plus the starter's case, job, health and metrics routes)
- the same file on `w7-scan-dispatch` serves only the starter's routes
- the same file on `feat/c-search-model-evaluation` adds only `POST /search`

## The contract as it stands

| Endpoint | Who calls it | Served today by | Decision needed |
| --- | --- | --- | --- |
| `POST /search` | the search UI | C | C's route reads C's own tables; it needs B's tables first (see `handover-to-C.md`) |
| `GET /mounts`, `GET /mounts/{id}` | the front end, to offer the folder picker | **nobody** | A has the allowlist in config; the route is A's |
| `POST /roots`, `GET /roots/{id}` | the front end | **B only** | A's branch does not have these; B's do exist. Keep B's and let A own the final shape |
| `GET /files?root_id=` | the front end, to list a folder | **nobody** | A (or B) - listing files is read-only and needs no AI |
| `GET /files/{id}/evidence?version_id=` | the front end, to show the source passage | **nobody** | B's handler reads **one chunk by id**; this route asks for a version and returns a list. Someone has to define which chunks it returns |
| `GET /jobs/{id}` | the front end, for progress | starter | already in every branch |
| health, metrics | operations | every branch | — |

## The two missing route families

**`/mounts`** is small: A's `source_mounts` allowlist already exists in
`services/common/config.py`, so the route is a read of that dict. It belongs to
A because it exposes deployment configuration.

**`/files?root_id=`** needs a decision about what a "file" looks like to the
UI: B's `files` row has `name`, `relative_path`, `presence_status` and
`current_version_id`, and the version has `status` and `error_code`. Returning
those four fields would let the UI show "queued, extracting, ready, unsupported,
failed" without inventing a second vocabulary.

**`/files/{id}/evidence?version_id=`** is the interesting one. B's handler answers
"give me chunk X", which is what a search result needs. The front end is asking
"give me the passages of version V of file F", which is a different question:
it wants the page-level evidence for a document that was just parsed. Either
the route returns all chunks of that version (bounded), or the UI switches to
fetching a specific chunk. That is a product decision, not a coding one - and it
is exactly where D's mock and B's handler disagree.

## What B can serve immediately

- `POST /roots` and `GET /roots/{id}` already exist on B's branch, with the
  ownership/status vocabulary A's decision record adopts.
- `read_evidence(db, chunk_id)` exists and refuses stale, missing or revoked
  sources with reason codes; wrapping it in a route is a few lines for A.
- `read_relationships(db, version_id)` and `record_review(...)` exist as
  handlers for the relation and review pages.

## Suggested order before the 10.21 freeze

1. A publishes the route list and payload shapes above, and implements
   `/mounts` and the two `/files` routes.
2. C re-parents its migration after B's head and remaps its queries onto B's
   files/versions/chunks (`handover-to-C.md`).
3. D points the adapter at whatever A finally publishes; its mock adapter
   already isolates that change.
4. B keeps its handlers as they are and adds tests only for whatever shape A
   chooses for `/files/{id}/evidence`.

The merge conflicts between C and B are mechanically resolvable. The missing
routes are not: they are the difference between four working branches and one
working product.
