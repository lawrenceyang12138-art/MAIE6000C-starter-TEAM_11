# Team 11 · Member A Decision Record (2026-10-16)

Owner: Member A (Lin) · Status: Final
Basis: `docs/architecture.md` on `origin/week04-architecture-proposal` (technical design authority) and B's `submissions/week07/handover-to-A.md`

---

## D1 — Who sets `files.current_version_id` → **The scan transaction**

**Decision**: set inside the scan (`scan_root`) transaction, pointing at the FileVersion observed in that scan.

**Rationale** (week04 `docs/architecture.md`):

- "`current_version_id` points to the latest observed content" — the pointer tracks *observed* content, not *parsed* content. Observation happens in workflow step 4, the scan ("persists its location and content version").
- "Until its text is ready, metadata/status remain visible but old passages/edges are historical, not current search results" — the spec explicitly tolerates a "pointed-at but not yet parsed" window. The intermediate state is carried by `version.status` (discovered / extracting) and by the evidence side's 409 `version_superseded`; the pointer does not wait for text.
- "A late worker cannot publish active outputs or restore an older current pointer" — if extraction set the pointer, the window would leave it NULL or on an older version, violating this rule.

**Implementation rules**:

- New observed content → create FileVersion(discovered) → point `files.current_version_id` at it in the **same transaction** (satisfies "a file's current version belongs to that file", validated inside the publication transaction).
- A file that disappeared (`presence_status=missing`): keep the old pointer, do not move it.
- Unchanged content (same SHA-256): reuse the existing version row; create nothing, move nothing.
- Same content at different paths are separate FileRecords; the hash is used for version idempotency only, never for deduplication or deletion.

**Scope**: `services/scan/handler.py` (scan transaction); unblocks B's evidence read path (503 `no_current_version`).

## D2 — Relation schema (four tables) → **Adopted as-is, no changes**

`entities` / `relationships` / `relationship_evidence` / `reviews` (migrations `318ab5be35e0` + `445f908b73b4`) are adopted unchanged. B's code and migrations are built on them, and B's handover forbids silent column edits. Any future column change is proposed by A, followed by B, and lands as a migration after both sides confirm.

## D3 — Mounts and path resolution → **Server-side allowlist**

- Config: `services/common/config.py` gains `source_mounts` (mount_id → container path), default `{"corpus": "/source/corpus"}`; `compose.yaml` mounts the corpus into the api and worker services as `:ro`; adding a mount requires a config change and a restart.
- Unknown mount_id → 403.
- Resolution: look up mount_id in the allowlist → join the root and file relative paths → normalise (reject absolute paths and `..`) → realpath containment double-check (bounded by both the mount and the authorized root).
- Spec basis: "A server-side allowlist maps a stable mount_id to that container path…Adding a new mount requires explicit configuration and a service restart"; "every scan, preview, and processing step rechecks canonical containment within both the configured mount and selected root"; "Symlink/junction escapes are rejected; a read-only mount alone is not sufficient authorization".

## D4 — Scan does not filter by extension

Discovery skips dotfiles and symlinks; everything else enters the pipeline (including unsupported formats such as .txt). Whether a document can be parsed is decided by extraction, not by its filename. Unsupported documents are recorded as version `unsupported` with an error_code, so failures stay visible. Spec basis: the fixed corpus deliberately contains one unsupported file, and the exception path requires "visible skipped/error reasons".

## D5 — Duplicate-dispatch protection and job state mapping

- Dispatch `extract_file` only for **newly created** FileVersions; a repeated scan adds nothing, including job rows.
- Job mapping: a deterministic document outcome from the handler (parsed / unsupported) → job completed; version recorded failed → job failed, with the error truncated into the row; failed jobs are retried through the retry action.
- Spec basis: "suppress duplicate active jobs for the same target/type"; "Reuse records for unchanged location/content"; exception path "processing → failed → visible reason → bounded retry".
