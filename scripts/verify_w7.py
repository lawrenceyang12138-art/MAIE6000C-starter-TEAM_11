"""Verify the W7 fixture workflow through a real HTTP API, Worker and database.

Run against a dedicated acceptance stack with read-only mounts:
``corpus`` = Compose's 16-file corpus and ``relations`` = tests/fixtures/relations.
The script authorizes/reuses only these explicit roots, queues scans and appends
synthetic review decisions. It never resets a database or writes source files.
Database connections issue SELECTs only. Restart, AI disconnect and source-change
scenarios are intentionally separate; this report does not claim to run them.

Example::

    python scripts/verify_w7.py --base-url http://127.0.0.1:18081 \
        --source-root tests/fixtures --out work/w7-http-db.json

Set W7_DATABASE_URL or pass --database-url. Credentials are excluded from reports
and exception output. Marker expectations below come from the checked-in PDF
fixture contract, not from search results.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlsplit

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Engine, make_url

REPO = Path(__file__).resolve().parents[1]
TERMINAL_VERSIONS = {"basic_ready", "enriched", "unsupported", "failed"}
TERMINAL_JOBS = {"completed", "failed"}
ABNORMAL = {
    "abnormal/corrupt.pdf": "corrupt",
    "abnormal/encrypted.pdf": "encrypted",
    "abnormal/no_text_layer.pdf": "no_text_layer",
    "regression/unsupported.txt": "unsupported_format",
}
# Independent fixed inputs: tests/integration/test_extraction_regression.py
# describes MarkerNNPp, embedded in these PDFs before retrieval is evaluated.
KEYWORD_GOLD = (
    ("Marker01P1", "regression/group-a/doc01.pdf", 1),
    ("Marker02P2", "regression/group-a/doc02.pdf", 2),
    ("Marker06P3", "regression/group-a/doc06.pdf", 3),
    ("Marker09P2", "regression/group-b/doc09.pdf", 2),
    ("Marker12P3", "regression/group-b/doc12.pdf", 3),
)
FILE_SCOPE = "SELECT id FROM files WHERE root_id = :root_id"
VERSION_SCOPE = f"SELECT id FROM file_versions WHERE file_id IN ({FILE_SCOPE})"
CHUNK_SCOPE = f"SELECT id FROM source_chunks WHERE version_id IN ({VERSION_SCOPE})"
RELATION_SCOPE = (
    f"SELECT id FROM relationships WHERE source_version_id IN ({VERSION_SCOPE})"
)
QUERIES = {
    "files": "SELECT id, relative_path, current_version_id, presence_status "
             "FROM files WHERE root_id = :root_id ORDER BY relative_path",
    "versions": "SELECT id, file_id, content_sha256, byte_size, status, error_code "
                f"FROM file_versions WHERE file_id IN ({FILE_SCOPE}) ORDER BY id",
    "chunks": "SELECT id, version_id, ordinal, page_number, text "
              f"FROM source_chunks WHERE version_id IN ({VERSION_SCOPE}) ORDER BY id",
    "keyword_indexes": "SELECT chunk_id FROM chunk_search_index "
                       f"WHERE chunk_id IN ({CHUNK_SCOPE}) ORDER BY chunk_id",
    "token_indexes": "SELECT chunk_id FROM chunk_token_search_index "
                     f"WHERE chunk_id IN ({CHUNK_SCOPE}) ORDER BY chunk_id",
    "page_metadata": "SELECT version_id FROM version_page_search_metadata "
                     f"WHERE version_id IN ({VERSION_SCOPE}) ORDER BY version_id",
    "jobs": "SELECT id, root_id, version_id, job_type, status, attempts, error_code "
            f"FROM jobs WHERE root_id = :root_id OR version_id IN ({VERSION_SCOPE}) "
            "ORDER BY id",
    "relationships": "SELECT id, source_version_id, object_entity_id "
                     f"FROM relationships WHERE id IN ({RELATION_SCOPE}) ORDER BY id",
    "reviews": "SELECT id, relationship_id, decision, decision_revision, corrected_entity_id "
               f"FROM reviews WHERE relationship_id IN ({RELATION_SCOPE}) "
               "ORDER BY relationship_id, decision_revision",
}


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def safe_database_identity(database_url: str) -> str:
    parsed = make_url(database_url)
    return URL.create(drivername=parsed.drivername, host=parsed.host, port=parsed.port,
                      database=parsed.database).render_as_string()


def source_paths(source_root: Path) -> dict[str, Path]:
    paths = {
        p.relative_to(source_root).as_posix(): p
        for p in sorted((source_root / "regression").rglob("*")) if p.is_file()
    }
    paths.update({
        f"abnormal/{name}": source_root / "parsing" / name
        for name in ("corrupt.pdf", "encrypted.pdf", "no_text_layer.pdf")
    })
    paths["relations/entities.pdf"] = source_root / "relations" / "entities.pdf"
    return paths


def hash_sources(paths: dict[str, Path]) -> dict[str, dict]:
    result = {}
    for name, path in paths.items():
        raw = path.read_bytes()
        result[name] = {"sha256": hashlib.sha256(raw).hexdigest(), "byte_size": len(raw)}
    return result


def guard_output(path: Path, source_root: Path, database_url: str) -> None:
    target = path.resolve()
    for protected in (source_root.resolve(), REPO / "fixtures", REPO / "tests/fixtures"):
        if target == protected or target.is_relative_to(protected):
            raise ValueError("report output must not overwrite a source fixture")
    database = make_url(database_url)
    if database.get_backend_name() == "sqlite" and database.database:
        if target == Path(database.database).resolve():
            raise ValueError("report output must not overwrite the database")
    if target.name in {"gold-queries.json", "gold-queries.freeze.json", "manifest.json"}:
        raise ValueError("report output must not overwrite a frozen input")
    if target.suffix.lower() != ".json":
        raise ValueError("report output must be a .json file")


def snapshot(engine: Engine, root_id: str) -> dict[str, list[dict]]:
    with engine.connect() as connection, connection.begin():
        if engine.dialect.name == "postgresql":
            connection.execute(text("SET TRANSACTION READ ONLY"))
        return {
            name: [dict(row) for row in connection.execute(
                text(sql), {"root_id": root_id}
            ).mappings()]
            for name, sql in QUERIES.items()
        }


def is_settled(state: dict) -> bool:
    versions, jobs = state["versions"], state["jobs"]
    if not state["files"] or not versions or not jobs:
        return False
    ready_ids = {v["id"] for v in versions if v["status"] in {"basic_ready", "enriched"}}
    indexed_ids = {j["version_id"] for j in jobs if j["job_type"] == "embed_file"}
    return (
        all(v["status"] in TERMINAL_VERSIONS for v in versions)
        and all(j["status"] in TERMINAL_JOBS for j in jobs)
        and ready_ids <= indexed_ids
    )


def index_job_coverage(jobs: list[dict], ready_version_ids: set[str]) -> bool:
    """Allow completed recovery indexing, while rejecting missing or duplicate live work."""
    embedding_jobs = [job for job in jobs if job["job_type"] == "embed_file"]
    live_counts = Counter(
        job["version_id"] for job in embedding_jobs if job["status"] in {"pending", "claimed"}
    )
    return (
        {job["version_id"] for job in embedding_jobs} == ready_version_ids
        and all(count <= 1 for count in live_counts.values())
    )


def identity_sets(state: dict) -> dict[str, list]:
    return {
        name: sorted(row[key] for row in state[name])
        for name, key in (
            ("files", "id"), ("versions", "id"), ("chunks", "id"),
            ("keyword_indexes", "chunk_id"), ("token_indexes", "chunk_id"),
            ("page_metadata", "version_id"), ("relationships", "id"), ("reviews", "id"),
        )
    }


class CheckFailed(RuntimeError):
    pass


class Verification:
    def __init__(self, client: httpx.Client, engine: Engine, args: argparse.Namespace):
        self.client, self.engine, self.args = client, engine, args
        self.report = {
            "schema_version": "team11-w7-http-db-v1", "started_at": now(),
            "base_url": args.base_url, "database": safe_database_identity(args.database_url),
            "source_root": str(args.source_root.resolve()),
            "keyword_gold_source": "checked-in regression MarkerNNPp fixture contract",
            "keyword_gold": KEYWORD_GOLD, "checks": [], "http": [],
            "limitations": [
                "No restart, AI disconnect/timeout, source-change or crash recovery in this script",
                "No human gold review or team signature supplied",
                "Review decisions are appended to the dedicated synthetic relations root",
            ],
        }

    def check(self, name: str, condition: bool, **evidence) -> None:
        self.report["checks"].append({
            "name": name, "passed": bool(condition), "at": now(), "evidence": evidence,
        })
        if not condition:
            raise CheckFailed(name)

    def phase(self, name: str, action: Callable) -> bool:
        try:
            action()
            return True
        except CheckFailed:
            return False
        except Exception as exc:
            # SQLAlchemy/HTTP exception strings can contain credentials or
            # deployment paths. The exception class and named step suffice.
            self.report["checks"].append({
                "name": name, "passed": False, "at": now(),
                "evidence": {"exception_type": type(exc).__name__},
            })
            return False

    def request(self, method: str, path: str, status: int = 200, **kwargs):
        response = self.client.request(method, path, **kwargs)
        try:
            body = response.json()
        except ValueError:
            body = {"content_type": response.headers.get("content-type", "")}
        self.report["http"].append({"method": method, "path": path,
                                    "status": response.status_code, "body": body})
        self.check(f"{method} {path} returns {status}", response.status_code == status,
                   actual_status=response.status_code)
        return body

    def wait(self, root_id: str) -> dict:
        deadline = time.monotonic() + self.args.timeout
        previous = None
        state = {}
        while time.monotonic() < deadline:
            state = snapshot(self.engine, root_id)
            signature = [(j["id"], j["status"]) for j in state["jobs"]]
            if is_settled(state) and previous == signature:
                self.check("all extraction AND embedding jobs reached terminal states", True,
                           root_id=root_id, jobs=state["jobs"])
                return state
            previous = signature if is_settled(state) else None
            time.sleep(min(self.args.poll_seconds, max(0, deadline - time.monotonic())))
        self.check("worker settles before deadline", False, root_id=root_id,
                   jobs=state.get("jobs", []), versions=state.get("versions", []))
        raise CheckFailed("worker timeout")

    def authorize(self, mount: str, relative_path: str) -> str:
        accepted = self.request("POST", "/roots", 202,
                                json={"mount_id": mount, "relative_path": relative_path})
        self.check("authorization returns pending job and identities",
                   bool(accepted.get("root_id")) and isinstance(accepted.get("job_id"), int)
                   and accepted.get("status") == "pending", accepted=accepted)
        self.request("GET", f"/jobs/{accepted['job_id']}")
        return accepted["root_id"]

    def setup_checks(self) -> None:
        self.request("GET", "/health/ready")
        mounts = self.request("GET", "/mounts")
        for mount in (self.args.mount, self.args.relation_mount):
            self.check(f"mount {mount} is explicit and read-only",
                       any(m["mount_id"] == mount and m["read_only"] for m in mounts))
            self.request("GET", f"/mounts/{mount}/directories")
        with self.engine.connect() as connection:
            self.check("database is PostgreSQL", self.engine.dialect.name == "postgresql")
            self.report["database_version"] = connection.execute(text("SELECT version()")).scalar()
            self.report["vector_extension_version"] = connection.execute(text(
                "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
            )).scalar()
            heads = list(connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalars())
            self.check("database has one applied Alembic head", len(heads) == 1, heads=heads)

    def corpus_checks(self, state: dict, hashes: dict) -> None:
        self.report["initial_state"] = state
        self.check("canonical corpus has exactly 16 files and versions",
                   len(state["files"]) == len(state["versions"]) == 16,
                   files=len(state["files"]), versions=len(state["versions"]))
        self.check("all queued jobs completed successfully",
                   all(j["status"] == "completed" for j in state["jobs"]), jobs=state["jobs"])
        versions = {v["id"]: v for v in state["versions"]}
        outcome = Counter()
        for file in state["files"]:
            version = versions[file["current_version_id"]]
            path = file["relative_path"]
            self.check(f"source identity and current pointer: {path}",
                       file["presence_status"] == "present" and path in hashes
                       and version["file_id"] == file["id"]
                       and version["content_sha256"] == hashes[path]["sha256"]
                       and version["byte_size"] == hashes[path]["byte_size"])
            expected = ABNORMAL.get(path)
            if expected:
                self.check(f"handled abnormal outcome: {path}",
                           version["status"] == "unsupported" and version["error_code"] == expected
                           and not any(c["version_id"] == version["id"] for c in state["chunks"]))
                outcome["unsupported"] += 1
            else:
                self.check(f"normal PDF is ready: {path}",
                           version["status"] in {"basic_ready", "enriched"}
                           and version["error_code"] is None)
                outcome["ready"] += 1
        self.check("12 ready and 4 unsupported", outcome == {"ready": 12, "unsupported": 4},
                   counts=dict(outcome))
        chunk_ids = {c["id"] for c in state["chunks"]}
        self.check("keyword indexes cover every source chunk", bool(chunk_ids) and chunk_ids == {
            i["chunk_id"] for i in state["keyword_indexes"]
        }, chunks=len(chunk_ids), keyword_indexes=len(state["keyword_indexes"]))
        extraction_jobs = [j for j in state["jobs"] if j["job_type"] == "extract_file"]
        self.check("one extract_file job per eligible version",
                   len(extraction_jobs) == len({j["version_id"] for j in extraction_jobs}) == 16
                   and {j["version_id"] for j in extraction_jobs} == set(versions))
        ready_ids = {v["id"] for v in state["versions"]
                     if v["status"] in {"basic_ready", "enriched"}}
        self.check("embedding jobs cover exactly ready versions without duplicate live work",
                   index_job_coverage(state["jobs"], ready_ids),
                   ready_version_ids=sorted(ready_ids),
                   embedding_jobs=[j for j in state["jobs"] if j["job_type"] == "embed_file"])

    def evidence_matches(self, hit: dict) -> None:
        evidence = self.request("GET", f"/evidence/{hit['chunk_id']}")
        self.check("search hit and source evidence identities/text match", all((
            evidence["chunk_id"] == hit["chunk_id"], evidence["file_id"] == hit["file_id"],
            evidence["version_id"] == hit["version_id"], evidence["page_number"] == hit["page"],
            evidence["ordinal"] == hit["ordinal"], evidence["relative_path"] == hit["file_path"],
            evidence["text"] == hit["text"],
        )), chunk_id=hit["chunk_id"])

    def search_checks(self, root_id: str, state: dict) -> None:
        for query, expected_path, page in KEYWORD_GOLD:
            result = self.request("POST", "/search", json={
                "query": query, "mode": "keyword", "root_id": root_id, "top_k": 10,
            })
            hits = result["results"]
            self.check(f"keyword Top-1: {query}", bool(hits)
                       and hits[0]["file_path"] == expected_path and hits[0]["page"] == page
                       and query in hits[0]["text"] and result["effective_mode"] == "keyword"
                       and not result["degraded"], expected_path=expected_path, expected_page=page)
            self.check("search deduplicates files", len(hits) == len({h["file_id"] for h in hits}))
            for hit in hits:
                self.evidence_matches(hit)
        files = {f["id"]: f for f in state["files"]}
        versions = {v["id"]: v for v in state["versions"]}
        for chunk in state["chunks"]:
            file = files[versions[chunk["version_id"]]["file_id"]]
            number = int(Path(file["relative_path"]).stem.removeprefix("doc"))
            marker = f"Marker{number:02d}P{chunk['page_number']}"
            self.check("stored source marker matches its claimed page", marker in chunk["text"],
                       chunk_id=chunk["id"], marker=marker)
            self.evidence_matches({
                "chunk_id": chunk["id"], "file_id": file["id"],
                "version_id": chunk["version_id"], "page": chunk["page_number"],
                "ordinal": chunk["ordinal"], "file_path": file["relative_path"],
                "text": chunk["text"],
            })

    def relation_checks(self, hashes: dict) -> None:
        root_id = self.authorize(self.args.relation_mount, self.args.relation_path)
        self.report["relation_root_id"] = root_id
        before = self.wait(root_id)
        self.check("dedicated relation root contains only the synthetic entities PDF",
                   len(before["files"]) == len(before["versions"]) == 1
                   and before["files"][0]["relative_path"] == "entities.pdf"
                   and before["versions"][0]["content_sha256"]
                   == hashes["relations/entities.pdf"]["sha256"])
        version_id = before["versions"][0]["id"]
        relations = self.request("GET", f"/versions/{version_id}/relations")
        by_type = {r["entity_type"]: r for r in relations if not r["evidence_missing"]}
        self.check("normal extraction generated person/project/topic candidates",
                   {"person", "project", "topic"} <= by_type.keys(),
                   entity_types=sorted(by_type))
        for relation in relations:
            self.check("relation has directly addressable evidence",
                       bool(relation["chunk_id"]) and not relation["evidence_missing"])
            evidence = self.request("GET", f"/evidence/{relation['chunk_id']}")
            self.check("relation evidence matches version/page/quote",
                       evidence["version_id"] == version_id
                       and evidence["page_number"] == relation["page_number"]
                       and " ".join(relation["quote"].split())
                       in " ".join(evidence["text"].split()),
                       relationship_id=relation["relationship_id"])
        written = []
        for kind, decision in (("person", "confirmed"), ("project", "corrected"),
                               ("topic", "rejected")):
            relation = by_type[kind]
            payload = {"decision": decision, "expected_revision": relation["decision_revision"],
                       "actor": "w7-http-db-verifier", "reason": "Synthetic acceptance check"}
            if decision == "corrected":
                payload["corrected_entity_id"] = by_type["person"]["entity_id"]
            receipt = self.request("POST", f"/relations/{relation['relationship_id']}/reviews",
                                   json=payload)
            self.check("review receipt has same relation and incremented revision",
                       receipt["relationship_id"] == relation["relationship_id"]
                       and receipt["decision"] == decision
                       and receipt["decision_revision"] == relation["decision_revision"] + 1,
                       receipt=receipt)
            written.append(receipt)
        stale_relation = by_type["person"]
        stale = self.request("POST", f"/relations/{stale_relation['relationship_id']}/reviews", 409,
                             json={"decision": "rejected", "actor": "w7-http-db-verifier",
                                   "expected_revision": stale_relation["decision_revision"]})
        self.check("stale write is a review_conflict", stale["detail"]["code"] == "review_conflict")
        after = snapshot(self.engine, root_id)
        old_ids = {r["id"] for r in before["reviews"]}
        new_reviews = [r for r in after["reviews"] if r["id"] not in old_ids]
        self.check("three new decisions append without deleting prior history",
                   old_ids <= {r["id"] for r in after["reviews"]} and len(new_reviews) == 3
                   and {r["decision"] for r in new_reviews}
                   == {"confirmed", "corrected", "rejected"},
                   appended=new_reviews)
        refreshed = self.request("GET", f"/versions/{version_id}/relations")
        current = {r["relationship_id"]: r for r in refreshed}
        self.check("readback exposes every saved effective decision", all(
            current[r["relationship_id"]]["decision"] == r["decision"]
            and current[r["relationship_id"]]["decision_revision"] == r["decision_revision"]
            for r in written
        ))
        self.report["relation_state"] = after

    def rescan_checks(self, root_id: str, before: dict) -> None:
        accepted = self.request("POST", f"/roots/{root_id}/scans", 202)
        self.check("rescan keeps root identity and queues a pending job",
                   accepted["root_id"] == root_id and accepted["status"] == "pending")
        after = self.wait(root_id)
        self.report["repeat_state"] = after
        self.check("rescan preserves all files/version/chunk/index/relation/review IDs",
                   identity_sets(before) == identity_sets(after),
                   before=identity_sets(before), after=identity_sets(after))
        before_jobs = {j["id"]: j for j in before["jobs"]}
        added = [j for j in after["jobs"] if j["id"] not in before_jobs]
        self.check("rescan adds exactly its one scan job, no extraction/embedding work",
                   len(added) == 1 and added[0]["id"] == accepted["job_id"]
                   and added[0]["job_type"] == "scan_root" and added[0]["status"] == "completed"
                   and before_jobs.keys() <= {j["id"] for j in after["jobs"]}, added_jobs=added)
        self.check("all rescan jobs completed",
                   all(j["status"] == "completed" for j in after["jobs"]))

    def operational_checks(self) -> None:
        self.request("GET", "/health/ready")
        response = self.client.get("/metrics")
        self.check("Prometheus metrics include HTTP and search signals", response.status_code == 200
                   and "api_http_requests_total" in response.text
                   and "api_search_requests_total" in response.text)
        self.report["metrics"] = response.text

    def run(self) -> dict:
        paths = source_paths(self.args.source_root)
        before_hashes = {}
        try:
            before_hashes = hash_sources(paths)
            self.check("local fixture set has 16 corpus files plus relation sample",
                       len(before_hashes) == 17, paths=sorted(before_hashes))
            self.report["originals_before"] = before_hashes
            self.phase("startup and database checks", self.setup_checks)
            root_id = self.authorize(self.args.mount, self.args.path)
            self.report["root_id"] = root_id
            state = self.wait(root_id)
            if self.phase("canonical corpus", lambda: self.corpus_checks(state, before_hashes)):
                self.phase("keyword and source evidence",
                           lambda: self.search_checks(root_id, state))
                self.phase("idempotent rescan", lambda: self.rescan_checks(root_id, state))
            self.phase("relations and append-only reviews",
                       lambda: self.relation_checks(before_hashes))
            self.phase("operational signals", self.operational_checks)
        except CheckFailed:
            pass
        except Exception as exc:
            self.report["checks"].append({"name": "workflow", "passed": False,
                                          "evidence": {"exception_type": type(exc).__name__}})
        finally:
            if before_hashes:
                def verify_originals():
                    after_hashes = hash_sources(paths)
                    self.report["originals_after"] = after_hashes
                    self.check("original source SHA-256 and byte sizes remain unchanged",
                               before_hashes == after_hashes)
                self.phase("original source verification", verify_originals)
        self.report["finished_at"] = now()
        checks = self.report["checks"]
        self.report["passed"] = bool(checks) and all(c["passed"] for c in checks)
        self.report["summary"] = {"passed": sum(c["passed"] for c in checks),
                                   "failed": sum(not c["passed"] for c in checks)}
        return self.report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--database-url", default=os.getenv("W7_DATABASE_URL")
                        or os.getenv("SEARCH_TEST_DATABASE_URL") or os.getenv("DATABASE_URL"))
    parser.add_argument("--source-root", type=Path, default=REPO / "tests/fixtures")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mount", default="corpus")
    parser.add_argument("--path", default=".")
    parser.add_argument("--relation-mount", default="relations")
    parser.add_argument("--relation-path", default=".")
    parser.add_argument("--timeout", type=float, default=600)
    parser.add_argument("--poll-seconds", type=float, default=1)
    args = parser.parse_args(argv)
    if not args.database_url:
        parser.error("set W7_DATABASE_URL or supply --database-url")
    try:
        base = urlsplit(args.base_url)
        if base.scheme not in {"http", "https"} or not base.hostname or base.username \
                or base.password or base.query or base.fragment:
            raise ValueError("base URL must be an HTTP endpoint without credentials/query/fragment")
        if args.timeout <= 0 or not 0 < args.poll_seconds <= 10:
            raise ValueError("timeout must be positive and poll-seconds must be in (0, 10]")
        guard_output(args.out, args.source_root, args.database_url)
        engine = create_engine(args.database_url, echo=False, pool_pre_ping=True)
    except Exception as exc:
        print(f"Invalid verification configuration ({type(exc).__name__}).")
        return 1
    try:
        # Explicit Origin also exercises the legitimate local-browser write path.
        origin = f"{base.scheme}://{base.netloc}"
        with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=30,
                          headers={"Origin": origin}) as client:
            report = Verification(client, engine, args).run()
        try:
            commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO,
                                    capture_output=True, text=True, check=True)
            report["commit"] = commit.stdout.strip()
            changes = subprocess.run(["git", "status", "--short", "--untracked-files=normal"],
                                     cwd=REPO, capture_output=True, text=True, check=True)
            report["working_tree_changes"] = changes.stdout.splitlines()
        except (OSError, subprocess.CalledProcessError):
            report["commit"] = None
        report["verification_script_sha256"] = hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest()
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str) + "\n",
                            encoding="utf-8")
        print(json.dumps({"passed": report["passed"],
                          "checks_passed": report["summary"]["passed"],
                          "checks_failed": report["summary"]["failed"],
                          "report": str(args.out.resolve())}))
        return 0 if report["passed"] else 1
    except Exception as exc:
        print(f"Verification could not finish ({type(exc).__name__}).")
        return 1
    finally:
        engine.dispose()


if __name__ == "__main__":
    raise SystemExit(main())
