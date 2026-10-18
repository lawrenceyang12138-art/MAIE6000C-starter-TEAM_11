"""Run API/AI/worker on isolated loopback ports, test HTTP then actually stop AI."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
from contextlib import ExitStack
from pathlib import Path

import httpx

from services.search.text import DIMENSIONS, MODEL_ID

REPO = Path(__file__).resolve().parents[1]


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
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError("Verification service exited; inspect work/search-http logs")
        try:
            if client.get(url + "/health/ready", timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError("Verification service did not become ready")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", default="sqlite:///work/search-demo.db")
    parser.add_argument("--model-path", default="models/multilingual-e5-small")
    parser.add_argument("--output", type=Path, default=Path("work/http-check.json"))
    parser.add_argument(
        "--pytest-output",
        type=Path,
        help="Run the complete pytest suite, including live smoke, and save JUnit XML",
    )
    args = parser.parse_args()
    gold = json.loads((REPO / "fixtures/search/gold-queries.json").read_text(encoding="utf-8"))
    ai_port, api_port = reserve_port(), reserve_port()
    ai_url, api_url = f"http://127.0.0.1:{ai_port}", f"http://127.0.0.1:{api_port}"
    environment = {
        **os.environ,
        "DATABASE_URL": args.database_url,
        "AI_SERVICE_URL": ai_url,
        "EMBEDDING_ENABLED": "true",
        "EMBEDDING_MODEL_PATH": args.model_path,
        "USE_TF": "0",
        "HF_HUB_OFFLINE": "1",
        "TRANSFORMERS_OFFLINE": "1",
        "WORKER_POLL_SECONDS": "0.2",
    }
    (REPO / "work/search-http").mkdir(parents=True, exist_ok=True)
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with ExitStack() as stack:
        processes = []
        for name, module, port in [
            ("ai", "services.ai.app.main:app", ai_port),
            ("api", "services.api.app.main:app", api_port),
        ]:
            log = stack.enter_context((REPO / f"work/search-http/{name}.log").open("w"))
            process = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    module,
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=REPO,
                env=environment,
                stdout=log,
                stderr=subprocess.STDOUT,
                creationflags=flags,
            )
            stack.callback(stop, process)
            processes.append(process)
        client = stack.enter_context(httpx.Client(timeout=15, trust_env=False))
        await_ready(client, ai_url, processes[0])
        await_ready(client, api_url, processes[1])
        warm = client.post(
            ai_url + "/embeddings", json={"texts": ["warm up"], "kind": "query"}, timeout=60
        )
        warm.raise_for_status()
        assert warm.json()["model"] == MODEL_ID and warm.json()["dimensions"] == DIMENSIONS
        print("Real local AI model ready; checking 10 queries", flush=True)
        before = []
        for query in gold["queries"]:
            response = client.post(api_url + "/search", json={"query": query["query"]})
            response.raise_for_status()
            data = response.json()
            assert data["effective_mode"] == "hybrid" and not data["degraded"]
            assert len({hit["file_id"] for hit in data["results"]}) == len(data["results"])
            before.append({"id": query["id"], "response": data})
        # Confirm the original starter worker path still works before shutting AI down.
        worker_log = stack.enter_context((REPO / "work/search-http/worker.log").open("w"))
        worker = subprocess.Popen(
            [sys.executable, "-m", "services.worker.app.main"],
            cwd=REPO,
            env=environment,
            stdout=worker_log,
            stderr=subprocess.STDOUT,
            creationflags=flags,
        )
        stack.callback(stop, worker)
        case_response = client.post(
            api_url + "/cases",
            json={
                "title": "C regression login check",
                "description": "User cannot access dashboard",
            },
        )
        case_response.raise_for_status()
        case_id = case_response.json()["case"]["id"]
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            case_data = client.get(api_url + "/cases/" + case_id).json()
            if case_data["status"] == "triaged":
                break
            time.sleep(0.2)
        assert case_data["status"] == "triaged" and case_data["ai_label"] == "access"
        if args.pytest_output is not None:
            args.pytest_output.parent.mkdir(parents=True, exist_ok=True)
            test_environment = {**environment, "SMOKE_BASE_URL": api_url}
            if args.database_url.startswith("postgresql"):
                test_environment["SEARCH_TEST_DATABASE_URL"] = args.database_url
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "-q",
                    "tests",
                    f"--junitxml={args.pytest_output.resolve()}",
                ],
                cwd=REPO,
                env=test_environment,
                check=True,
                creationflags=flags,
            )
        stop(worker)
        stop(processes[0])
        print("AI process stopped; checking 5 keyword fallbacks", flush=True)
        after = []
        for query in gold["queries"][:5]:
            response = client.post(api_url + "/search", json={"query": query["query"]})
            response.raise_for_status()
            data = response.json()
            assert (
                data["effective_mode"] == "keyword"
                and data["degradation_reason"] == "ai_unavailable"
            )
            hit = data["results"][0]
            assert hit["file_id"] == query["expected_file_id"]
            assert hit["page"] == query["expected_page"]
            after.append({"id": query["id"], "response": data})
        report = {
            "data_kind": "synthetic",
            "model": MODEL_ID,
            "dimensions": DIMENSIONS,
            "real_http_processes": True,
            "ai_process_terminated": True,
            "summary": {
                "hybrid_passed": len(before),
                "stopped_ai_keyword_passed": len(after),
                "starter_worker_case_flow": "passed",
                "pytest_complete_suite": "passed" if args.pytest_output else "not_requested",
            },
            "queries_before_stop": before,
            "queries_after_stop": after,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
