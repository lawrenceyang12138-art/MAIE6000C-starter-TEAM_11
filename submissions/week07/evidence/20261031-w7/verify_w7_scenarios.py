"""Live W7 checks using HTTP, PostgreSQL and disposable source copies.

Run ``versions`` while the worker runs normally. For deterministic recovery,
pause the worker container, run ``recovery-authorize``, execute that scan job
once with the worker code in the API container (same application image and
source mounts), run ``recovery-remove``, resume the worker, then run
``recovery-finish``. No parser/search implementation is mocked.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text


def now():
    return datetime.now(UTC).isoformat()


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Audit:
    def __init__(self, args):
        self.repo = Path(__file__).resolve().parents[1]
        # The evidence copy can also be executed from the repository root.
        if not (self.repo / "pyproject.toml").is_file():
            self.repo = Path.cwd().resolve()
        self.out = self.repo / args.out
        self.out.parent.mkdir(parents=True, exist_ok=True)
        self.data = (
            json.loads(self.out.read_text())
            if self.out.is_file()
            else {
                "started_at": now(),
                "base_url": args.base_url,
                "database": "PostgreSQL 16 + pgvector, isolated W7 audit database",
                "source_policy": (
                    "Only work/w7-audit-sources copies are modified; "
                    "container mounts are read-only."
                ),
                "state_injection": (
                    "Root lifecycle states are injected through SQL because W7 has no "
                    "lifecycle management route. Recovery failures use actual absent "
                    "source bytes and the real worker."
                ),
                "events": [],
            }
        )
        self.client = httpx.Client(base_url=args.base_url, timeout=20, trust_env=False)
        self.engine = create_engine(args.database_url)
        self.normal = self.repo / "tests/fixtures/parsing/normal.pdf"
        self.entities = self.repo / "tests/fixtures/relations/entities.pdf"
        self.originals = {
            str(p.relative_to(self.repo)): digest(p) for p in [self.normal, self.entities]
        }

    def save(self):
        self.data["updated_at"] = now()
        self.out.write_text(
            json.dumps(self.data, indent=2, ensure_ascii=False, default=str) + "\n",
            encoding="utf-8",
        )

    def request(self, label, method, path, *, expected=200, payload=None, record=True):
        response = self.client.request(method, path, json=payload)
        body = response.json()
        if record:
            self.data["events"].append(
                {
                    "at": now(),
                    "label": label,
                    "method": method,
                    "path": path,
                    "request": payload,
                    "status": response.status_code,
                    "body": body,
                }
            )
            self.save()
        assert response.status_code == expected, (label, response.status_code, body)
        return body

    def sql(self, statement, **params):
        with self.engine.begin() as connection:
            return [dict(row) for row in connection.execute(text(statement), params).mappings()]

    def snapshot(self, root_id):
        return {
            "files": self.sql(
                "SELECT id, current_version_id, presence_status FROM files WHERE root_id=:root",
                root=root_id,
            ),
            "versions": self.sql(
                "SELECT v.* FROM file_versions v JOIN files f ON f.id=v.file_id "
                "WHERE f.root_id=:root ORDER BY v.created_at",
                root=root_id,
            ),
            "chunks": self.sql(
                "SELECT c.id,c.version_id,c.ordinal,c.page_number FROM source_chunks c "
                "JOIN file_versions v ON v.id=c.version_id JOIN files f ON f.id=v.file_id "
                "WHERE f.root_id=:root ORDER BY c.version_id,c.ordinal",
                root=root_id,
            ),
            "jobs": self.sql(
                "SELECT id,job_type,status,attempts,error_code,version_id FROM jobs "
                "WHERE root_id=:root OR version_id IN (SELECT v.id FROM file_versions v "
                "JOIN files f ON f.id=v.file_id WHERE f.root_id=:root) ORDER BY id",
                root=root_id,
            ),
            "reviews": self.sql(
                "SELECT rv.id,rv.relationship_id,rv.decision_revision,rv.decision,"
                "rv.corrected_entity_id FROM reviews rv "
                "JOIN relationships r ON r.id=rv.relationship_id "
                "JOIN file_versions v ON v.id=r.source_version_id "
                "JOIN files f ON f.id=v.file_id WHERE f.root_id=:root "
                "ORDER BY rv.relationship_id,rv.decision_revision",
                root=root_id,
            ),
        }

    def wait_idle(self, root_id):
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            snap = self.snapshot(root_id)
            if snap["files"] and all(
                job["status"] in {"completed", "failed"} for job in snap["jobs"]
            ):
                assert all(
                    v["status"] not in {"discovered", "extracting"} for v in snap["versions"]
                ), snap
                return snap
            time.sleep(0.2)
        raise TimeoutError(f"root did not settle: {root_id}")

    def authorize(self, folder):
        return self.request(
            f"authorize_{folder}",
            "POST",
            "/roots",
            expected=202,
            payload={"mount_id": "scenarios", "relative_path": folder},
        )

    def search(self, root_id, query, *, label=None):
        return self.request(
            label or f"search_{query}",
            "POST",
            "/search",
            payload={"query": query, "mode": "keyword", "root_id": root_id},
        )

    def rescan(self, root_id, label):
        self.request(label, "POST", f"/roots/{root_id}/scans", expected=202)
        return self.wait_idle(root_id)

    def source(self, folder):
        path = self.repo / "work/w7-audit-sources" / folder / "document.pdf"
        assert path.resolve().is_relative_to((self.repo / "work/w7-audit-sources").resolve())
        return path

    def set_root(self, root_id, status):
        self.sql(
            "UPDATE authorized_roots SET status=:status WHERE id=:root RETURNING id",
            root=root_id,
            status=status,
        )
        self.data["events"].append(
            {
                "at": now(),
                "label": "root_state_injection",
                "root_id": root_id,
                "status": status,
                "mechanism": "direct SQL in isolated audit database",
            }
        )
        self.save()

    def versions(self):
        target = self.source("versions")
        assert digest(target) == digest(self.normal)
        accepted = self.data.get("versions")
        if accepted is None:
            accepted = self.authorize("versions")
        else:
            accepted = {"root_id": accepted["root_id"], "job_id": accepted["scan_job_id"]}
        root = accepted["root_id"]
        self.data["versions"] = {"root_id": root, "scan_job_id": accepted["job_id"]}
        self.save()
        first = self.wait_idle(root)
        hit = self.search(root, "ALPHA")["results"][0]
        self.request("initial_evidence", "GET", f"/evidence/{hit['chunk_id']}")
        original_version = hit["version_id"]
        shutil.copyfile(self.entities, target)
        second = self.rescan(root, "scan_changed_content")
        current = self.search(root, "Chen")["results"][0]
        assert current["version_id"] != original_version
        assert self.search(root, "ALPHA", label="old_text_excluded")["results"] == []
        stale = self.request(
            "old_version_refused", "GET", f"/evidence/{hit['chunk_id']}", expected=409
        )
        assert stale["detail"]["code"] == "version_superseded"
        self.request("new_version_evidence", "GET", f"/evidence/{current['chunk_id']}")

        target.write_bytes(target.read_bytes() + b"\n% unscanned edit\n")
        changed = self.request(
            "unscanned_edit_refused", "GET", f"/evidence/{current['chunk_id']}", expected=409
        )
        assert changed["detail"]["code"] == "source_changed"
        target.unlink()
        missing = self.request(
            "missing_source_refused", "GET", f"/evidence/{current['chunk_id']}", expected=404
        )
        assert missing["detail"]["code"] == "file_missing"
        shutil.copyfile(self.entities, target)
        repeat = self.rescan(root, "scan_restored_same_content")
        assert [v["id"] for v in repeat["versions"]] == [v["id"] for v in second["versions"]]
        assert repeat["chunks"] == second["chunks"]
        assert len([j for j in repeat["jobs"] if j["job_type"] != "scan_root"]) == len(
            [j for j in second["jobs"] if j["job_type"] != "scan_root"]
        )

        shutil.copyfile(self.normal, target)
        reverted = self.rescan(root, "scan_reverted_content")
        assert reverted["files"][0]["current_version_id"] == original_version
        self.request("reverted_original_evidence_restored", "GET", f"/evidence/{hit['chunk_id']}")
        assert len(reverted["versions"]) == 2
        assert reverted["chunks"] == second["chunks"]
        shutil.copyfile(self.entities, target)
        restored = self.rescan(root, "scan_return_to_known_second_version")
        assert restored["files"][0]["current_version_id"] == current["version_id"]
        assert len(restored["versions"]) == 2

        relations = self.request(
            "candidate_entities_discoverable", "GET", f"/versions/{current['version_id']}/relations"
        )
        relation = relations[0]
        replacement = next(item for item in relations if item["entity_id"] != relation["entity_id"])
        for revision, decision in enumerate(["confirmed", "corrected", "rejected"]):
            payload = {
                "decision": decision,
                "expected_revision": revision,
                "actor": "w7-backend-live-audit",
                "reason": "W7 live append-only review validation",
            }
            if decision == "corrected":
                payload["corrected_entity_id"] = replacement["entity_id"]
            review = self.request(
                f"live_review_{decision}",
                "POST",
                f"/relations/{relation['relationship_id']}/reviews",
                payload=payload,
            )
            assert review["decision_revision"] == revision + 1
        conflict = self.request(
            "stale_review_revision_refused",
            "POST",
            f"/relations/{relation['relationship_id']}/reviews",
            expected=409,
            payload={"decision": "confirmed", "expected_revision": 0},
        )
        assert conflict["detail"]["code"] == "review_conflict"

        self.set_root(root, "paused")
        try:
            self.request("paused_evidence_readable", "GET", f"/evidence/{current['chunk_id']}")
            assert self.search(root, "Chen", label="paused_search_readable")["results"]
            paused = self.request(
                "paused_rescan_refused", "POST", f"/roots/{root}/scans", expected=409
            )
            assert paused["detail"]["code"] == "root_paused"
        finally:
            self.set_root(root, "active")
        self.set_root(root, "revoked")
        try:
            revoked = self.request(
                "revoked_evidence_refused", "GET", f"/evidence/{current['chunk_id']}", expected=403
            )
            assert revoked["detail"]["code"] == "root_revoked"
            relations_refused = self.request(
                "revoked_relations_refused",
                "GET",
                f"/versions/{current['version_id']}/relations",
                expected=403,
            )
            assert relations_refused["detail"]["code"] == "root_revoked"
            assert self.search(root, "Chen", label="revoked_search_empty")["results"] == []
            assert self.request("revoked_file_list_hidden", "GET", f"/files?root_id={root}") == []
            roots = self.request("revoked_root_hidden", "GET", "/roots")
            assert root not in {item["root_id"] for item in roots}
        finally:
            self.set_root(root, "active")
        final = self.snapshot(root)
        assert len(final["reviews"]) == 3
        self.data["versions"].update(
            {
                "passed": True,
                "initial": first,
                "after_change": second,
                "after_restoration": repeat,
                "final": final,
                "current_evidence_chunk_id": current["chunk_id"],
                "initial_evidence_chunk_id": hit["chunk_id"],
                "review_relationship_id": relation["relationship_id"],
            }
        )

    def recovery_authorize(self):
        accepted = self.authorize("recovery")
        self.data["recovery"] = {
            "root_id": accepted["root_id"],
            "scan_job_id": accepted["job_id"],
            "control": (
                "Worker container paused; accepted scan claimed and dispatched once "
                "with the worker code in the API container (same application image, "
                "database and read-only source mounts), before removing source copy."
            ),
        }
        print(json.dumps(self.data["recovery"]))

    def recovery_remove(self):
        state = self.data["recovery"]
        snap = self.snapshot(state["root_id"])
        assert len(snap["files"]) == len(snap["versions"]) == 1
        extract = [job for job in snap["jobs"] if job["job_type"] == "extract_file"]
        assert len(extract) == 1 and extract[0]["status"] == "pending", snap
        state.update({"after_scan": snap, "extract_job_id": extract[0]["id"]})
        self.source("recovery").unlink()
        state["source_removed_at"] = now()
        print("Recovery source copy removed; resume worker main loop now.")

    def recovery_finish(self):
        state = self.data["recovery"]
        root, job_id = state["root_id"], state["extract_job_id"]
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            job = self.request("poll_recovery", "GET", f"/jobs/{job_id}", record=False)
            if job["status"] == "failed":
                break
            time.sleep(0.2)
        assert job["status"] == "failed" and job["error_code"] == "file_missing", job
        state["failed_job"] = self.request("real_source_loss_failed_job", "GET", f"/jobs/{job_id}")
        state["failed_snapshot"] = self.snapshot(root)
        shutil.copyfile(self.entities, self.source("recovery"))
        rescanned = self.rescan(root, "scan_is_not_implicit_retry")
        assert rescanned["versions"][0]["id"] == state["after_scan"]["versions"][0]["id"]
        assert rescanned["versions"][0]["status"] == "failed"
        assert len([j for j in rescanned["jobs"] if j["job_type"] == "extract_file"]) == 1
        self.request(
            "explicit_retry_real_failed_extract", "POST", f"/jobs/{job_id}/retry", expected=202
        )
        final = self.wait_idle(root)
        result = self.search(root, "Chen", label="recovered_keyword_search")
        assert result["results"]
        evidence = self.request(
            "recovered_source_evidence", "GET", f"/evidence/{result['results'][0]['chunk_id']}"
        )
        assert evidence["content_sha256"] == digest(self.entities)
        completed = self.request("recovered_job_attempts_preserved", "GET", f"/jobs/{job_id}")
        assert completed["status"] == "completed" and completed["attempts"] == 2
        assert final["files"][0]["id"] == state["after_scan"]["files"][0]["id"]
        assert len(final["versions"]) == 1
        assert len([j for j in final["jobs"] if j["job_type"] == "extract_file"]) == 1
        assert len([j for j in final["jobs"] if j["job_type"] == "embed_file"]) == 1
        state.update(
            {
                "passed": True,
                "after_rescan_before_retry": rescanned,
                "final": final,
                "current_evidence_chunk_id": evidence["chunk_id"],
            }
        )

    def finish(self):
        assert self.originals == {
            str(p.relative_to(self.repo)): digest(p) for p in [self.normal, self.entities]
        }
        self.data["fixture_hashes_unchanged"] = self.originals
        self.save()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "stage", choices=["versions", "recovery-authorize", "recovery-remove", "recovery-finish"]
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:18081")
    parser.add_argument(
        "--database-url", default="postgresql+psycopg://postgres:postgres@127.0.0.1:15481/maie6000c"
    )
    parser.add_argument(
        "--out", default="submissions/week07/evidence/20261031-w7/backend-scenarios.json"
    )
    args = parser.parse_args()
    audit = Audit(args)
    try:
        getattr(audit, args.stage.replace("-", "_"))()
        audit.finish()
    except Exception as exc:
        audit.data["failure"] = {"stage": args.stage, "at": now(), "error": repr(exc)}
        audit.save()
        raise


if __name__ == "__main__":
    main()
