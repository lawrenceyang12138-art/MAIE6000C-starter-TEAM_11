"""Record live local-AI recovery, HTTP failure, timeout, and PDF evidence checks.

Use a disposable database already populated by scripts.evaluate_team_pdf. Only
existing indexing commands write vectors; this tool never changes frozen answers,
source bytes, root authorization, or canonical file/version/chunk identities.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time
from contextlib import ExitStack
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.exc import SQLAlchemyError

from scripts.evaluate_team_pdf import (
    dependency_versions,
    digest,
    git_state,
    public_command,
    validate_corpus,
    validate_report_destination,
)
from services.common.db import make_engine, make_session_factory
from services.common.models import FileRecord, FileVersion, SourceChunk
from services.search.text import MODEL_DIRECTORY, MODEL_ID, TOKEN_DIMENSIONS
from services.search.token_store import ChunkTokenIndex, index_matches_text

REPO = Path(__file__).resolve().parents[1]

if not __debug__:
    raise SystemExit("Runtime verification relies on assert; do not run with -O")


def reserve_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def stop(process: subprocess.Popen) -> None:
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def await_ready(client: httpx.Client, url: str, process: subprocess.Popen) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("service_exited_before_ready")
        try:
            if client.get(url + "/health/ready", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.2)
    raise RuntimeError("service_ready_timeout")


def source_snapshot(database_url: str, root_id: str) -> dict:
    engine = make_engine(database_url)
    try:
        with make_session_factory(engine)() as db:
            records = list(db.execute(
                select(SourceChunk, FileRecord, FileVersion)
                .join(FileVersion, FileVersion.id == SourceChunk.version_id)
                .join(FileRecord, FileRecord.id == FileVersion.file_id)
                .where(FileRecord.root_id == root_id,
                       FileRecord.current_version_id == FileVersion.id)
                .order_by(FileRecord.relative_path, SourceChunk.ordinal)
            ))
            compatible = [
                index for chunk, _, _ in records
                if (index := db.get(ChunkTokenIndex, chunk.id)) is not None
                and index_matches_text(index, chunk.text)
            ]
            return {
                "chunks": [{
                    "chunk_id": chunk.id, "version_id": version.id,
                    "file_id": file.id, "relative_path": file.relative_path,
                    "page": chunk.page_number, "text": chunk.text,
                    "content_sha256": version.content_sha256,
                } for chunk, file, version in records],
                "vectors": len(compatible),
                "token_vectors": sum(index.token_count for index in compatible),
                "representation": "token_multivector",
                "token_dimensions": TOKEN_DIMENSIONS,
            }
    finally:
        engine.dispose()


def run_index(database_url: str, version_id: str, ai_url: str, timeout: float) -> dict:
    command = [
        sys.executable, "-m", "scripts.search_tools", "index",
        "--database-url", database_url, "--version-id", version_id,
        "--backend", "http", "--ai-url", ai_url, "--timeout", str(timeout),
    ]
    completed = subprocess.run(command, cwd=REPO, capture_output=True, text=True,
                               encoding="utf-8", timeout=180, check=False)
    return {"command": public_command(command), "returncode": completed.returncode,
            "result": json.loads(completed.stdout), "stderr": completed.stderr}


def checked_search(client: httpx.Client, api_url: str, corpus: Path,
                   payload: dict) -> dict:
    started = time.monotonic()
    response = client.post(api_url + "/search", json=payload)
    response.raise_for_status()
    data = response.json()
    evidence_rows = []
    for hit in data["results"]:
        if hit["root_id"] != payload["root_id"]:
            raise RuntimeError("search_result_out_of_scope")
        evidence_response = client.get(api_url + "/evidence/" + hit["chunk_id"])
        evidence_response.raise_for_status()
        evidence = evidence_response.json()
        source = (corpus / evidence["relative_path"]).resolve()
        if not source.is_relative_to(corpus.resolve()):
            raise RuntimeError("evidence_path_out_of_scope")
        valid = (
            evidence["file_id"] == hit["file_id"]
            and evidence["version_id"] == hit["version_id"]
            and evidence["chunk_id"] == hit["chunk_id"]
            and evidence["page_number"] == hit["page"]
            and evidence["relative_path"] == hit["file_path"]
            and evidence["ordinal"] == hit["ordinal"]
            and evidence["text"][:2000] == hit["text"]
            and digest(source) == evidence["content_sha256"]
        )
        if not valid:
            raise RuntimeError("evidence_identity_mismatch")
        evidence_rows.append({"http_status": evidence_response.status_code,
                              "identity_and_source_hash_verified": valid,
                              "response": evidence})
    if len({item["file_id"] for item in data["results"]}) != len(data["results"]):
        raise RuntimeError("duplicate_search_files")
    return {"request": payload, "http_status": response.status_code,
            "seconds": round(time.monotonic() - started, 4),
            "response": data, "evidence": evidence_rows}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--model-path", type=Path,
                        default=REPO / MODEL_DIRECTORY)
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--output", type=Path, default=REPO / "work/team-runtime.json")
    args = parser.parse_args()
    try:
        validate_report_destination(
            args.output,
            protected_files=[args.evaluation, REPO / "submissions/week07/gold-queries.json",
                             REPO / "submissions/week07/gold-queries.freeze.json",
                             REPO / "fixtures/manifest.json"],
            source_directories=[REPO / "fixtures"],
        )
    except ValueError as exc:
        parser.error(str(exc))
    prior = json.loads(args.evaluation.read_text(encoding="utf-8"))
    root_id, mount_id = prior["pipeline"]["root_id"], prior["pipeline"]["mount_id"]
    corpus = Path(prior["corpus_directory"])
    try:
        validate_report_destination(
            args.output, protected_files=[], source_directories=[corpus],
        )
    except ValueError as exc:
        parser.error(str(exc))
    gold_path = REPO / "submissions/week07/gold-queries.json"
    freeze_path = REPO / "submissions/week07/gold-queries.freeze.json"
    gold = json.loads(gold_path.read_text("utf-8"))
    freeze = json.loads(freeze_path.read_text("utf-8"))
    manifest_path = REPO / "fixtures/manifest.json"
    manifest = json.loads(manifest_path.read_text("utf-8"))
    if not (digest(gold_path) == prior["answer_version"]["gold_sha256"] == freeze["gold_sha256"]
            and digest(manifest_path) == prior["answer_version"]["manifest_sha256"]
            == freeze["manifest_sha256"]):
        raise SystemExit("Frozen answers/corpus differ from the evaluated database's report")
    snapshot = source_snapshot(args.database_url, root_id)
    versions = sorted({item["version_id"] for item in snapshot["chunks"]})
    if not versions:
        raise SystemExit("No parsed PDF chunks; run scripts.evaluate_team_pdf first")
    report = {
        "created_at": datetime.now(timezone.utc).isoformat(), "git": git_state(),
        "runtime": {"python": platform.python_version(), "packages": dependency_versions()},
        "command": public_command([
            sys.executable, "-m", "scripts.verify_team_search_runtime", *sys.argv[1:]
        ]),
        "database": make_url(args.database_url).render_as_string(hide_password=True),
        "root_id": root_id, "corpus_directory": str(corpus),
        "answer_version": prior["answer_version"],
        "evaluation_input_sha256": digest(args.evaluation),
        "http_timeout_seconds": args.timeout,
        "timeout_probe_delay_seconds": args.timeout + 0.5,
        "initial_vector_chunks": snapshot["vectors"],
        "initial_token_vectors": snapshot["token_vectors"],
        "model": MODEL_ID,
        "dimensions": TOKEN_DIMENSIONS,
        "representation": "token_multivector",
        "scoring": "maxsim_mean",
        "warmup_timeout_seconds": max(120, args.timeout + 5),
        "index_subprocess_timeout_seconds": 180,
        "source_identity_sha256": hashlib.sha256(
            json.dumps(snapshot["chunks"], sort_keys=True).encode("utf-8")
        ).hexdigest(),
        "quality_results": "See frozen PDF evaluation; protocol checks do not imply quality hits",
        "passed": False,
    }
    resolved_by_query = {
        item["query_id"]: item["resolved"] for item in prior["source_resolutions"]
    }

    def annotate(row: dict, query: dict) -> dict:
        resolved = resolved_by_query[query["query_id"]]
        response = row["response"]
        cutoff = 1 if row["request"]["mode"] == "keyword" else 3
        ranks = [
            rank for rank, hit in enumerate(response["results"], 1)
            if any(location["ready"]
                   and hit["file_id"] == location["file_id"]
                   and hit["version_id"] == location["version_id"]
                   and hit["page"] == location["page"] for location in resolved)
        ]
        located = any(rank <= cutoff for rank in ranks)
        row.update(
            query_id=query["query_id"], expected=query["expected"], resolved_expected=resolved,
            matched_rank=min(ranks) if ranks else None, location_hit=located,
            hit=located and not response["degraded"],
        )
        return row
    log_dir = REPO / "work/team-runtime-logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    ai_port, api_port = reserve_port(), reserve_port()
    while api_port == ai_port:
        api_port = reserve_port()
    ai_url, api_url = f"http://127.0.0.1:{ai_port}", f"http://127.0.0.1:{api_port}"
    environment = {
        **os.environ, "DATABASE_URL": args.database_url, "AI_SERVICE_URL": ai_url,
        "EMBEDDING_ENABLED": "true", "EMBEDDING_MODEL_PATH": str(args.model_path.resolve()),
        "SEARCH_REQUEST_TIMEOUT_SECONDS": str(args.timeout),
        "SOURCE_MOUNTS": json.dumps({mount_id: str(corpus)}),
        "HF_HUB_OFFLINE": "1", "TRANSFORMERS_OFFLINE": "1", "USE_TF": "0",
    }
    try:
        corpus_before = validate_corpus(corpus, manifest)
        with ExitStack() as stack:
            def launch(name: str, module: str, port: int) -> subprocess.Popen:
                log = stack.enter_context((log_dir / f"{name}.log").open("w", encoding="utf-8"))
                process = subprocess.Popen(
                    [sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1",
                     "--port", str(port)], cwd=REPO, env=environment,
                    stdout=log, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
                )
                stack.callback(stop, process)
                return process

            client = stack.enter_context(httpx.Client(timeout=max(120, args.timeout + 5),
                                                      trust_env=False))
            report["stage"] = "index_while_ai_disconnected"
            report["failed_index_before_ai"] = run_index(
                args.database_url, versions[0], ai_url, args.timeout
            )
            failed = report["failed_index_before_ai"]
            assert failed["returncode"] == 1
            assert failed["result"]["embedding_error"] == "ai_unavailable"
            assert source_snapshot(args.database_url, root_id)["chunks"] == snapshot["chunks"]
            ai = launch("ai", "services.ai.app.main:app", ai_port)
            api = launch("api", "services.api.app.main:app", api_port)
            await_ready(client, ai_url, ai)
            await_ready(client, api_url, api)
            report["stage"] = "warm_local_model"
            warm = client.post(ai_url + "/embeddings", json={"texts": ["warm up"], "kind": "query"})
            warm.raise_for_status()
            assert warm.json()["model"] == MODEL_ID
            assert warm.json()["dimensions"] == TOKEN_DIMENSIONS
            assert warm.json()["representation"] == "token_multivector"
            assert warm.json()["scoring"] == "maxsim_mean"
            report["warmup"] = {"model": warm.json()["model"],
                                "dimensions": warm.json()["dimensions"],
                                "representation": warm.json()["representation"],
                                "scoring": warm.json()["scoring"],
                                "query_token_count": len(warm.json()["vectors"][0])}
            report["initial_recovery_commands"] = []
            report["stage"] = "backfill_current_pdf_versions"
            for version in versions:
                indexed = run_index(args.database_url, version, ai_url, args.timeout)
                report["initial_recovery_commands"].append(indexed)
                assert indexed["returncode"] == 0 and indexed["result"]["embedding_error"] is None
            recovered = source_snapshot(args.database_url, root_id)
            assert recovered["chunks"] == snapshot["chunks"]
            assert recovered["vectors"] == len(snapshot["chunks"])
            report["recovered_vector_chunks"] = recovered["vectors"]
            report["recovered_token_vectors"] = recovered["token_vectors"]
            report["online_queries"] = []
            report["stage"] = "live_api_search_and_evidence"
            for query in gold["queries"]:
                modes = ["keyword"] if query["kind"] == "keyword" else ["semantic", "hybrid"]
                for mode in modes:
                    row = checked_search(client, api_url, corpus, {
                        "query": query["query"], "mode": mode, "root_id": root_id, "top_k": 3,
                    })
                    annotate(row, query)
                    report["online_queries"].append(row)
                    assert row["response"]["effective_mode"] == mode
                    assert not row["response"]["degraded"]
            stop(ai)
            query = gold["queries"][0]["query"]
            report["disconnected"] = []
            report["stage"] = "live_ai_disconnected"
            for mode in ["keyword", "semantic", "hybrid"]:
                row = checked_search(client, api_url, corpus, {
                    "query": query, "mode": mode, "root_id": root_id, "top_k": 3,
                })
                data = row["response"]
                assert data["mode"] == mode and data["effective_mode"] == "keyword"
                assert bool(data["results"]) and data["degraded"] == (mode != "keyword")
                if mode != "keyword":
                    assert data["degradation_reason"] == "ai_unavailable"
                annotate(row, gold["queries"][0])
                report["disconnected"].append(row)

            class SlowHandler(BaseHTTPRequestHandler):
                def do_POST(self):
                    time.sleep(args.timeout + 0.5)
                    try:
                        self.send_response(503)
                        self.end_headers()
                    except OSError:
                        pass

                def log_message(self, *arguments):
                    pass

            slow = ThreadingHTTPServer(("127.0.0.1", ai_port), SlowHandler)
            thread = threading.Thread(target=slow.serve_forever, daemon=True)
            thread.start()
            try:
                report["timed_out"] = []
                report["stage"] = "live_ai_timeout"
                for mode in ["semantic", "hybrid"]:
                    row = checked_search(client, api_url, corpus, {
                        "query": query, "mode": mode, "root_id": root_id, "top_k": 3,
                    })
                    data = row["response"]
                    assert data["mode"] == mode and data["effective_mode"] == "keyword"
                    assert data["degraded"] and data["degradation_reason"] == "ai_timeout"
                    assert data["results"]
                    annotate(row, gold["queries"][0])
                    report["timed_out"].append(row)
            finally:
                slow.shutdown()
                slow.server_close()
                thread.join(timeout=2)
            ai = launch("ai-restored", "services.ai.app.main:app", ai_port)
            report["stage"] = "ai_restored"
            await_ready(client, ai_url, ai)
            warm = client.post(
                ai_url + "/embeddings", json={"texts": ["restored"], "kind": "query"}
            )
            warm.raise_for_status()
            report["restored_index_command"] = run_index(
                args.database_url, versions[0], ai_url, args.timeout
            )
            assert report["restored_index_command"]["returncode"] == 0
            report["restored_search"] = checked_search(client, api_url, corpus, {
                "query": query, "mode": "hybrid", "root_id": root_id, "top_k": 3,
            })
            annotate(report["restored_search"], gold["queries"][0])
            assert not report["restored_search"]["response"]["degraded"]
            final = source_snapshot(args.database_url, root_id)
            report["source_identities_unchanged"] = final["chunks"] == snapshot["chunks"]
            corpus_after = validate_corpus(corpus, manifest)
            report["corpus_files"] = corpus_after
            report["all_corpus_bytes_unchanged"] = corpus_before == corpus_after
            report["final_vector_chunks"] = final["vectors"]
            report["final_token_vectors"] = final["token_vectors"]
            assert report["source_identities_unchanged"] and report["all_corpus_bytes_unchanged"]
            report["stage"] = "complete"
            report["passed"] = True
    except (OSError, ValueError, RuntimeError, AssertionError, httpx.HTTPError,
            subprocess.SubprocessError, SQLAlchemyError) as exc:
        report["failure"] = {"exception_type": type(exc).__name__,
                             "message": str(exc) if isinstance(exc, RuntimeError) else None}
    finally:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps({key: report.get(key) for key in [
        "passed", "failure", "initial_vector_chunks", "recovered_vector_chunks",
        "final_vector_chunks", "source_identities_unchanged",
    ]}, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
