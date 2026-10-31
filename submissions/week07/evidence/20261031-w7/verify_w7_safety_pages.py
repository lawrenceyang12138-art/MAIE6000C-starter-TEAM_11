from pathlib import Path
import json
import os
import hashlib
import uuid
from datetime import datetime, UTC
import httpx
import pymupdf
from sqlalchemy import create_engine, text

base_url = "http://127.0.0.1:18081"
root_id = "fdf4ab46-b7ea-4bff-96bd-6fd496272134"
fixture_root = Path("tests/fixtures/regression")
output = Path("submissions/week07/evidence/20261031-w7/runtime-safety-pages.json")
engine = create_engine(os.environ["W7_DATABASE_URL"], echo=False)
sentinel = "w7-refused-" + uuid.uuid4().hex
report = {
    "schema_version": "team11-w7-runtime-safety-pages-v1",
    "started_at": datetime.now(UTC).isoformat(),
    "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    "base_url": base_url,
    "root_id": root_id,
    "database": "isolated PostgreSQL 16 / pgvector acceptance database",
    "page_reader": {
        "tool": "PyMuPDF",
        "version": pymupdf.VersionBind,
        "policy": "Independent physical PDF pages; no product parser invoked",
    },
    "safety": [],
    "physical_pages": [],
    "checks": [],
}


def check(name, passed, **evidence):
    report["checks"].append({"name": name, "passed": bool(passed), "evidence": evidence})
    if not passed:
        raise AssertionError(name)


def snapshot():
    with engine.connect() as db:
        result = {
            "global_counts": {
                t: db.scalar(text("SELECT count(*) FROM " + t))
                for t in ("authorized_roots", "jobs", "reviews")
            }
        }
        result["canonical_scan_jobs"] = list(
            db.execute(
                text(
                    "SELECT id FROM jobs WHERE root_id=:root AND job_type='scan_root' ORDER BY id"
                ),
                {"root": root_id},
            ).scalars()
        )
        result["canonical_reviews"] = list(
            db.execute(
                text(
                    "SELECT r.id FROM reviews r JOIN relationships a ON r.relationship_id=a.id "
                    "JOIN file_versions v ON a.source_version_id=v.id "
                    "JOIN files f ON v.file_id=f.id "
                    "WHERE f.root_id=:root ORDER BY r.id"
                ),
                {"root": root_id},
            ).scalars()
        )
        result["illegal_roots"] = list(
            db.execute(
                text(
                    "SELECT id FROM authorized_roots WHERE mount_id=:invalid_mount "
                    "OR relative_path=:invalid_path"
                ),
                {"invalid_mount": sentinel, "invalid_path": "../" + sentinel},
            ).scalars()
        )
        return result


normal = {"mount_id": "corpus", "relative_path": "."}
cases = [
    ("external_host", {"host": "attacker.invalid"}, normal, 403, "invalid_host"),
    ("userinfo_host", {"host": "attacker@localhost"}, normal, 403, "invalid_host"),
    ("external_origin", {"origin": "https://attacker.invalid"}, normal, 403, "origin_not_allowed"),
    ("null_origin", {"origin": "null"}, normal, 403, "origin_not_allowed"),
    ("cross_site_fetch", {"sec-fetch-site": "cross-site"}, normal, 403, "origin_not_allowed"),
    ("simple_form", {"content-type": "text/plain"}, normal, 403, "origin_not_allowed"),
    (
        "traversal",
        {},
        {"mount_id": "corpus", "relative_path": "../" + sentinel},
        403,
        "path_out_of_scope",
    ),
    ("unknown_mount", {}, {"mount_id": sentinel, "relative_path": "."}, 404, "unknown_mount"),
]
try:
    report["database_before"] = snapshot()
    with httpx.Client(
        base_url=base_url,
        headers={"origin": base_url},
        timeout=15,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        for name, headers, payload, status, code in cases:
            kwargs = {"headers": headers}
            if name == "simple_form":
                kwargs["content"] = json.dumps(payload)
            else:
                kwargs["json"] = payload
            response = client.post("/roots", **kwargs)
            body = response.json()
            report["safety"].append(
                {
                    "name": name,
                    "method": "POST",
                    "path": "/roots",
                    "request_headers": headers,
                    "request_body": payload,
                    "status": response.status_code,
                    "body": body,
                }
            )
            check(name, response.status_code == status and body["detail"]["code"] == code)
    report["database_after"] = snapshot()
    before, after = report["database_before"], report["database_after"]
    for field in ("canonical_scan_jobs", "canonical_reviews", "illegal_roots"):
        check(
            "No persistent writes from rejected requests: " + field,
            before[field] == after[field] and (field != "illegal_roots" or not after[field]),
            before=before[field],
            after=after[field],
        )
    report["global_counts_unchanged"] = before["global_counts"] == after["global_counts"]
    report["concurrency_policy"] = (
        "Global counts are observational because other browser/model "
        "acceptance may write concurrently. Rejected root requests target canonical root and "
        "unique illegal mount/path; their scan-job/review IDs "
        "and illegal-root absence are asserted."
    )
    with engine.connect() as db:
        rows = [
            dict(row)
            for row in db.execute(
                text(
                    "SELECT c.id chunk_id,c.version_id,c.page_number,c.ordinal,c.text,"
                    "f.relative_path,v.content_sha256,v.byte_size FROM source_chunks c "
                    "JOIN file_versions v ON c.version_id=v.id JOIN files f ON v.file_id=f.id "
                    "WHERE f.root_id=:root ORDER BY f.relative_path,c.ordinal"
                ),
                {"root": root_id},
            ).mappings()
        ]
    check("Canonical database contains 30 source chunks", len(rows) == 30)
    documents = {}
    for row in rows:
        remote = row["relative_path"]
        local = fixture_root / Path(remote).relative_to("regression")
        if remote not in documents:
            raw = local.read_bytes()
            doc = pymupdf.open(stream=raw, filetype="pdf")
            documents[remote] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "byte_size": len(raw),
                "pages": [p.get_text() for p in doc],
            }
            doc.close()
        source = documents[remote]
        page = row["page_number"]
        identity = (
            source["sha256"] == row["content_sha256"] and source["byte_size"] == row["byte_size"]
        )
        check("Independent source hash and size match stored version: " + remote, identity)
        check("Claimed physical page exists: " + row["chunk_id"], 0 < page <= len(source["pages"]))
        physical = source["pages"][page - 1]
        def normalized(value):
            return " ".join(value.split())

        marker = f"Marker{int(local.stem.removeprefix('doc')):02d}P{page}"
        located = marker in row["text"] and marker in physical
        text_match = normalized(row["text"]) in normalized(physical)
        report["physical_pages"].append(
            {
                "chunk_id": row["chunk_id"],
                "version_id": row["version_id"],
                "relative_path": remote,
                "page_number": page,
                "physical_page_count": len(source["pages"]),
                "marker": marker,
                "source_sha256": source["sha256"],
                "source_identity_matches": identity,
                "marker_matches_physical_page": located,
                "chunk_is_physical_page_substring": text_match,
                "verified_fragment": normalized(row["text"]),
            }
        )
        check(
            "Chunk text and marker match independent physical page: " + row["chunk_id"],
            located and text_match,
        )
    report["physical_documents"] = {
        path: {k: v for k, v in doc.items() if k != "pages"} for path, doc in documents.items()
    }
    report["physical_page_score"] = f"{len(report['physical_pages'])}/30"
except Exception as exc:
    report["failure"] = {"type": type(exc).__name__}
    if isinstance(exc, AssertionError):
        report["failure"]["check"] = str(exc)
finally:
    report["finished_at"] = datetime.now(UTC).isoformat()
    report["passed"] = "failure" not in report and all(c["passed"] for c in report["checks"])
    report["summary"] = {
        "checks_passed": sum(c["passed"] for c in report["checks"]),
        "checks_failed": sum(not c["passed"] for c in report["checks"]),
        "safety_refusals": len(report["safety"]),
        "physical_chunks_verified": len(report["physical_pages"]),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    engine.dispose()
    print(json.dumps({"passed": report["passed"], **report["summary"], "output": str(output)}))
    if not report["passed"]:
        raise SystemExit(1)
