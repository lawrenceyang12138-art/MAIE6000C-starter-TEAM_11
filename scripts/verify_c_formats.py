"""Check the mixed-format gate using real HTTP and read-only PostgreSQL observations."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from scripts import c_format_stack as stack
from scripts.c_format_fixtures import FORMATS, REPO, STAGE, SUITE, load, passage, stage
from scripts.c_search_suite import SuiteError, digest, require, validate_stage
from scripts.verify_w7 import TERMINAL_JOBS, TERMINAL_VERSIONS, snapshot

REPORTS = REPO / "work/c-format-validation/reports"


def fetch(client, log, method, path, status=200, **kwargs):
    res = client.request(method, path, **kwargs)
    item = {"method": method, "path": path, **kwargs, "status": res.status_code}
    log.append(item)
    try:
        item["response"] = res.json()
    except ValueError:
        item["response"] = None
    require(res.status_code == status and item["response"] is not None,
            f"{method} {path}: HTTP {res.status_code}; expected JSON and {status}")
    return item["response"]


def wait_scan(engine, root_id, job_id, timeout):
    stop = time.monotonic() + timeout
    while True:
        state = snapshot(engine, root_id)
        jobs = state["jobs"]
        if (any(j["id"] == job_id and j["job_type"] == "scan_root" and j["status"] == "completed"
                and j["attempts"] > 0 for j in jobs)
                and all(j["status"] in TERMINAL_JOBS for j in jobs)
                and all(v["status"] in TERMINAL_VERSIONS for v in state["versions"])):
            return state, True
        if time.monotonic() >= stop or any(j["id"] == job_id and j["status"] == "failed"
                                           for j in jobs):
            return state, False
        time.sleep(0.3)


def source_state(state, path):
    files = [f for f in state["files"] if f["relative_path"] == path]
    require(len(files) == 1, f"expected one file: {path}")
    file = files[0]
    versions = [v for v in state["versions"] if v["file_id"] == file["id"]]
    require(len(versions) == 1 and versions[0]["id"] == file["current_version_id"],
            f"expected one current version with no duplicate: {path}")
    return file, versions[0]


def verify_hit(hit, evidence, root_id, file, version, chunks, source, query, fmt):
    chunk = chunks.get(hit["chunk_id"])
    require(chunk is not None and hit["root_id"] == root_id, "wrong root or chunk")
    require((hit["file_id"], hit["version_id"], hit["file_path"]) ==
            (file["id"], version["id"], file["relative_path"]), "stale or wrong search hit")
    expected = {"file_id": file["id"], "version_id": version["id"],
                "relative_path": file["relative_path"], "chunk_id": chunk["id"],
                "ordinal": chunk["ordinal"], "page_number": query["page"],
                "content_sha256": version["content_sha256"], "text": chunk["text"]}
    require(all(k in evidence and evidence[k] == v for k, v in expected.items()),
            "evidence differs from the DB, file, version or expected page")
    require((hit["ordinal"], hit["page"], hit["text"]) ==
            (chunk["ordinal"], query["page"], chunk["text"])
            and chunk["page_number"] == hit["page"],
            "search text, ordinal or page differs from evidence")
    require(query["quote"] in chunk["text"] and passage(chunk["text"], fmt)
            in passage(source[query["page"]], fmt), "evidence not found in the original source")
    if fmt != "pdf":
        require("page navigation:" not in hit["reason"].lower(), "PDF page navigation applied")


def search(client, log, root, query, file_id=None):
    params = {"root_id": root, "query": query, "mode": "keyword", "top_k": 20}
    if file_id:
        params["file_id"] = file_id
    result = fetch(client, log, "POST", "/search", json=params)
    require(result["mode"] == result["effective_mode"] == "keyword" and not result["degraded"],
            "not an explicit keyword response")
    return result


def audit(client, log, state, listing, root, row, source):
    path = row["path"]
    fmt = path.split("/")[0]
    file, v = source_state(state, path)
    api_file = listing.get(path)
    require(api_file and (api_file["root_id"], api_file["file_id"], api_file["version_id"],
                          api_file["status"], api_file["error_code"], api_file["presence_status"])
            == (root, file["id"], v["id"], v["status"], v["error_code"], "present"),
            "file API and DB disagree")
    require(file["presence_status"] == "present" and v["content_sha256"] == row["sha256"]
            and v["byte_size"] == row["byte_size"], "source identity differs from original bytes")
    chunks = {c["id"]: c for c in state["chunks"] if c["version_id"] == v["id"]}
    jobs = [j for j in state["jobs"] if j["job_type"] == "extract_file" and j["version_id"]
            == v["id"] and j["attempts"] > 0]
    require(jobs, "missing real Worker extract attempt")
    metadata = [m for m in state["pdf_metadata"] if m["version_id"] == v["id"]]
    if fmt != "pdf":
        require(not metadata and all(c["page_number"] is None for c in chunks.values()),
                "non-PDF has physical page metadata or a fabricated chunk page")
    if row["kind"] == "negative":
        require(v["status"] in {"unsupported", "failed"}
                and v["error_code"] in row["expected_errors"]
                and not chunks, "bad sample not rejected cleanly with the expected reason")
        result = search(client, log, root, Path(path).name, file["id"])
        require(result["results"] == [] and result["total"] == 0, "bad file produced a hit")
        return f'{v["status"]}: {v["error_code"]}; zero chunks and hits'
    require(v["status"] == "basic_ready" and v["error_code"] is None
            and any(j["status"] == "completed" for j in jobs), "file did not reach basic_ready")
    require(chunks and set(chunks) <= {k["chunk_id"] for k in state["keyword_indexes"]},
            "ready chunks not keyword-indexed")
    require({c["page_number"] for c in chunks.values()} == {p for p, t in source.items()
            if t.strip()}, "blank/absent page has chunks or a source page is missing")
    if fmt == "pdf":
        require(len(metadata) == 1 and metadata[0]["page_count"] == row["page_count"]
                and metadata[0]["content_sha256"] == row["sha256"], "wrong physical PDF metadata")
    nav = state["page_probe"]
    decisions = [d for d in nav["diagnostics"]["files"] if d["version_id"] == v["id"]]
    allowed = {c["id"]: c["allowed"] for c in nav["chunks"].get(v["id"], [])}
    require(nav["active"] and set(allowed) == set(chunks), "active navigation probe unavailable")
    if fmt == "pdf":
        require(len(decisions) == 1 and decisions[0]["applied"] and
                all(allowed[i] == (c["page_number"] == 3) for i, c in chunks.items()),
                "physical page 3 navigation disagrees with the PDF control")
    else:
        require(not nav["pdf_metadata_lookups"].get(v["id"]) and all(allowed.values())
                and not any(d["applied"] or d["target_pages"]
                for d in decisions), "non-PDF routed to a physical PDF page")
    for q in row["queries"]:
        probes = [(q["keyword"], None)]
        if fmt != "pdf":
            probes.append((q["keyword"] + " page 97", file["id"]))
        for query_text, file_scope in probes:
            hits = search(client, log, root, query_text, file_scope)["results"]
            require([h["file_path"] for h in hits] == [path], "wrong or missing keyword match")
            hit = hits[0]
            ev = fetch(client, log, "GET", f'/evidence/{hit["chunk_id"]}')
            verify_hit(hit, ev, root, file, v, chunks, source, q, fmt)
    return "basic_ready; keyword + original evidence matched"


def execute(client, engine, args, report, suite):
    gold, plan, sources, _ = suite
    shared = report["http"]
    with engine.connect() as conn:
        ident = conn.execute(text("SELECT current_database() AS db, version() AS server, "
                                  "(SELECT version_num FROM alembic_version) AS migration, "
                                  "(SELECT count(*) FROM authorized_roots) AS roots, "
                                  "(SELECT count(*) FROM files) AS files")).mappings().one()
        require(ident["db"] == stack.DATABASE and ident["roots"] == ident["files"] == 0,
                "not the empty gate database")
        report["database"] = dict(ident)
    require(fetch(client, shared, "GET", "/setup")["state"] == "disabled", "AI not disabled")
    mounts = fetch(client, shared, "GET", "/mounts")
    require(len(mounts) == 1 and mounts[0]["mount_id"] == stack.MOUNT and mounts[0]["read_only"]
            and mounts[0]["availability"] == "available", "wrong API source mount")
    require(fetch(client, shared, "GET", "/roots") == [], "API not empty")
    report["runtime_checks_started"] = True
    job = fetch(client, shared, "POST", "/roots", 202, json={"mount_id": stack.MOUNT,
                                                            "relative_path": "."})
    root = report["root_id"] = job["root_id"]
    state, settled = wait_scan(engine, root, job["job_id"], args.timeout)
    report["first_scan"] = state
    require(settled, "first scan did not complete/settle; see first_scan jobs")
    require({f["relative_path"] for f in state["files"]} <= set(plan), "unexpected source in DB")
    with engine.connect() as conn:
        sql = ("SELECT m.version_id, m.page_count, m.content_sha256 "
               "FROM version_page_search_metadata m JOIN file_versions v ON v.id=m.version_id "
               "JOIN files f ON f.id=v.file_id WHERE f.root_id=:root")
        state["pdf_metadata"] = list(map(dict, conn.execute(text(sql), {"root": root}).mappings()))
    probe = REPO / "scripts/c_format_navigation_probe.py"
    with probe.open("rb") as script:
        state["page_probe"] = json.loads(stack.output("docker", "exec", "-i",
                                         report["containers"]["api"]["id"], "python", "-", root,
                                         stdin=script))
    files = fetch(client, shared, "GET", "/files", params={"root_id": root})
    listing = {f["relative_path"]: f for f in files}
    for path, case in report["cases"].items():
        if not case["in_scope"]:
            continue
        try:
            case["observed"] = audit(client, case["http"], state, listing, root, plan[path],
                                     sources.get(path))
        except (SuiteError, KeyError, TypeError) as exc:
            case.update(status="FAIL", observed=str(exc))
    absent = search(client, shared, root, gold["absent_keyword"])
    require(absent["results"] == [] and absent["total"] == 0, "absent keyword returned a hit")
    second = fetch(client, shared, "POST", f"/roots/{root}/scans", 202)
    require(second["root_id"] == root and second["job_id"] != job["job_id"], "not a new rescan")
    after, settled = wait_scan(engine, root, second["job_id"], args.timeout)
    report["rescan"] = after
    require(settled, "unchanged rescan did not settle; see rescan jobs")
    validate_stage(STAGE, plan)
    for path, case in report["cases"].items():
        if case["in_scope"] and case["status"] != "FAIL":
            try:
                before_file, before_v = source_state(state, path)
                new_file, new_v = source_state(after, path)
                require(before_file == new_file and before_v == new_v, "file/version changed")
                require({c["id"] for c in state["chunks"] if c["version_id"] == before_v["id"]}
                        == {c["id"] for c in after["chunks"] if c["version_id"] == new_v["id"]},
                        "unchanged rescan replaced evidence IDs")
                case.update(status="PASS", rescan="same file, version and chunks")
            except SuiteError as exc:
                case.update(status="FAIL", rescan=str(exc))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--candidate-sha", required=True, help="full Git commit supplied by A")
    p.add_argument("--flags", required=True, type=Path, help="A's non-secret parser flags file")
    p.add_argument("--formats", nargs="+", required=True, choices=FORMATS, help="PDF always runs")
    p.add_argument("--run-id", required=True, help="new short lower-case ID")
    p.add_argument("--api-port", type=int, default=18086)
    p.add_argument("--db-port", type=int, default=15486)
    p.add_argument("--timeout", type=int, default=120)
    args = p.parse_args(argv)
    if (not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,30}", args.run_id) or args.timeout < 1 or
            not all(0 < x < 65536 for x in (args.api_port, args.db_port)) or
            args.api_port == args.db_port or not re.fullmatch("[0-9a-f]{40}", args.candidate_sha)):
        p.error("invalid run ID, commit, ports or timeout")
    directory = REPORTS / args.run_id
    if directory.exists() or directory.resolve() != directory:
        p.error("report directory already exists or is redirected; use a fresh ID")
    directory.mkdir(parents=True)
    scope = set(args.formats) | {"pdf"}
    report = {"started": datetime.now(UTC).isoformat(), "candidate_sha": args.candidate_sha,
              "scope": sorted(scope), "cases": {}, "http": [], "status": "UNVERIFIED"}
    try:
        suite = load()
        gold, plan, _, raw = suite
        report["cases"] = {path: {"in_scope": path.split("/")[0] in scope, "status": "UNVERIFIED",
                                  "http": []} for path in plan}
        stage(plan, raw)
        report.update(archive_sha256=gold["archive_sha256"],
                      manifest_sha256=digest(SUITE / "manifest.json"),
                      flags_sha256=digest(args.flags),
                      verifier_sha256={p.name: digest(p) for p in (Path(__file__), stack.COMPOSE,
                                       REPO / "scripts/c_format_stack.py",
                                       REPO / "scripts/c_format_navigation_probe.py",
                                       REPO / "scripts/c_format_fixtures.py")})
        stack.start(args, report)
        base = f"http://127.0.0.1:{args.api_port}"
        url = f"postgresql+psycopg://postgres:postgres@127.0.0.1:{args.db_port}/{stack.DATABASE}"
        engine = create_engine(url, connect_args={"connect_timeout": 5}).execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True)
        try:
            with httpx.Client(base_url=base, timeout=10, trust_env=False) as client:
                execute(client, engine, args, report, suite)
        finally:
            engine.dispose()
        report["status"] = ("PASS" if all(c["status"] == "PASS" for c in report["cases"].values()
                                          if c["in_scope"]) else "FAIL")
    except SuiteError as exc:
        report["error"] = str(exc)
        if report.get("runtime_checks_started"):
            report["status"] = "FAIL"
    except (OSError, subprocess.SubprocessError, SQLAlchemyError, httpx.HTTPError,
            ValueError, KeyError, TypeError) as exc:
        report["error"] = type(exc).__name__
    report["formats"] = {}
    for fmt in FORMATS:
        outcomes = [c["status"] for path, c in report["cases"].items()
                    if path.startswith(fmt + "/")]
        report["formats"][fmt] = ("FAIL" if "FAIL" in outcomes else "PASS"
                                  if len(outcomes) == 3 and set(outcomes) == {"PASS"}
                                  else "UNVERIFIED")
    report["finished"] = datetime.now(UTC).isoformat()
    with (directory / "actual.json").open("x", encoding="utf-8") as out:
        json.dump(report, out, ensure_ascii=True, indent=2)
        out.write("\n")
    lines = ["| Format | Positive / negative case | Actual result | Candidate SHA | Evidence |",
             "| --- | --- | --- | --- | --- |"]
    if not report["cases"]:
        for fmt in FORMATS:
            lines.append(f"| {fmt} | No cases executed | UNVERIFIED | `{args.candidate_sha}` | "
                         "[preflight error](actual.json) |")
    for path, case in report["cases"].items():
        why = case.get("observed", "not run") if case["in_scope"] else "not in scope"
        fmt = path.split("/")[0]
        lines.append(f"| {fmt} ({report['formats'][fmt]}) | {path} | {case['status']}: {why}; "
                     f"{case.get('rescan', 'rescan not verified')} | `{args.candidate_sha}` | "
                     f"[actual.json](actual.json): cases / `{path}`; first_scan; rescan |")
    (directory / "handoff.md").write_text("\n".join(lines) + "\n\nRun: " + report["status"] +
                                         ". " + report.get("error", "") + "\n", encoding="utf-8")
    print(json.dumps({"status": report["status"], "error": report.get("error"),
                      "report": str(directory / "actual.json")}))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
