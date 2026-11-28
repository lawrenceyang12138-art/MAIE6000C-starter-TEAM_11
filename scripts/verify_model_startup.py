"""Record real startup progress, readiness, early-scan fallback and recovery.

Run before starting the isolated stack. No model files or databases are deleted.
The optional --exercise-corpus creates a normal authorized root in that stack.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

# Support the documented direct invocation from a clean checkout as well as
# python -m scripts.verify_model_startup.
if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.start import local_url
from services.search.embeddings import validate_vectors
from services.search.text import MODEL_ID


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def capture(args) -> dict:
    api, ai = local_url(args.api_url), local_url(args.ai_url)
    report = {
        "started_at": utc_now(), "model": MODEL_ID, "api_url": api, "ai_url": ai,
        "require_download": args.require_download, "timeline": [], "checks": {},
        "early_scan": None, "keyword_while_preparing": None, "semantic_while_preparing": None,
    }
    deadline = time.monotonic() + args.timeout
    previous = None
    last_recorded_bytes = -64 * 1024 * 1024
    root_id = None
    keyword = None
    source_before = source_hashes(args.source_root)
    with httpx.Client(timeout=5, trust_env=False) as client:
        while time.monotonic() < deadline:
            try:
                response = client.get(api + "/setup")
                response.raise_for_status()
                status = response.json()
                current = status["state"]
                if (current != previous or
                        status["downloaded_bytes"] - last_recorded_bytes >= 64 * 1024 * 1024):
                    report["timeline"].append({"observed_at": utc_now(), **status})
                    print(f"{current}: {status['downloaded_bytes']}/{status['total_bytes']}",
                          flush=True)
                    previous, last_recorded_bytes = current, status["downloaded_bytes"]
                if current not in {"ready", "error", "disabled", "unavailable"}:
                    live = client.get(ai + "/health/live")
                    ready = client.get(ai + "/health/ready")
                    report["checks"]["live_while_preparing"] = live.status_code == 200
                    report["checks"]["not_ready_while_preparing"] = ready.status_code == 503
                    if args.exercise_corpus and root_id is None:
                        result = client.post(api + "/roots", json={
                            "mount_id": "corpus", "relative_path": "regression",
                        })
                        result.raise_for_status()
                        report["early_scan"] = result.json()
                        root_id = result.json()["root_id"]
                    if root_id and report["keyword_while_preparing"] is None:
                        query = {"query": "doc01", "root_id": root_id, "top_k": 3}
                        response = client.post(api + "/search", json={**query, "mode": "keyword"})
                        response.raise_for_status()
                        keyword = response.json()
                        if keyword["results"]:
                            report["keyword_while_preparing"] = keyword
                            response = client.post(api + "/search",
                                                   json={**query, "mode": "semantic"})
                            response.raise_for_status()
                            report["semantic_while_preparing"] = response.json()
                            hit = keyword["results"][0]
                            evidence = client.get(api + "/evidence/" + hit["chunk_id"])
                            evidence.raise_for_status()
                            report["early_evidence"] = evidence.json()
                elif current == "ready":
                    report["ready_status"] = status
                    report["checks"]["ready_after_warmup"] = (
                        status["ready"] is True
                        and client.get(ai + "/health/ready").status_code == 200
                    )
                    break
                elif current in {"error", "disabled"}:
                    report["terminal_status"] = status
                    break
            except (httpx.HTTPError, ValueError, KeyError) as exc:
                # No response bodies, signed model URLs or exception text in evidence.
                report["last_observation_error"] = type(exc).__name__
            time.sleep(args.poll)

        if "ready_status" in report:
            for kind in ("query", "passage"):
                result = client.post(ai + "/embeddings",
                                     json={"texts": ["Local search verification."], "kind": kind},
                                     timeout=60)
                result.raise_for_status()
                payload = result.json()
                vectors = validate_vectors(payload["vectors"], 1)
                report["checks"][kind + "_inference"] = payload["model"] == MODEL_ID
                report[kind + "_shape"] = [len(vectors[0]), len(vectors[0][0])]
            if root_id:
                recover_deadline = time.monotonic() + 180
                while time.monotonic() < recover_deadline:
                    result = client.post(api + "/search", json={
                        "query": "doc01", "root_id": root_id,
                        "file_id": keyword["results"][0]["file_id"] if keyword else None,
                        "mode": "semantic", "top_k": 3,
                    }, timeout=30)
                    result.raise_for_status()
                    report["after_ready_semantic"] = result.json()
                    if not result.json()["degraded"] and result.json()["results"]:
                        report["checks"]["automatic_early_scan_recovery"] = True
                        hit = result.json()["results"][0]
                        evidence = client.get(api + "/evidence/" + hit["chunk_id"])
                        evidence.raise_for_status()
                        report["after_ready_evidence"] = evidence.json()
                        break
                    time.sleep(2)

    states = {item["state"] for item in report["timeline"]}
    report["checks"]["required_download_observed"] = (
        not args.require_download or "downloading" in states
    )
    report["checks"]["ready_observed"] = "ready_status" in report
    if args.exercise_corpus:
        report["checks"]["keyword_during_preparation"] = bool(report["keyword_while_preparing"])
        degraded = report["semantic_while_preparing"] or {}
        report["checks"]["explicit_semantic_fallback"] = (
            degraded.get("mode") == "semantic" and degraded.get("effective_mode") == "keyword"
            and degraded.get("degraded") is True and bool(degraded.get("degradation_reason"))
        )
        report["checks"].setdefault("automatic_early_scan_recovery", False)
    if args.source_root:
        report["source_sha256_before"] = source_before
        report["source_sha256_after"] = source_hashes(args.source_root)
        report["checks"]["original_sources_unchanged"] = (
            report["source_sha256_before"] == report["source_sha256_after"]
        )
    report["completed_at"] = utc_now()
    report["passed"] = all(report["checks"].values())
    return report


def source_hashes(root: Path | None) -> dict:
    if root is None:
        return {}
    checksums = {}
    for source in sorted(root.rglob("*")):
        if source.is_file():
            with source.open("rb") as stream:
                checksums[source.relative_to(root).as_posix()] = hashlib.file_digest(
                    stream, "sha256",
                ).hexdigest()
    return checksums


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://127.0.0.1:8000")
    parser.add_argument("--ai-url", default="http://127.0.0.1:8100")
    parser.add_argument("--timeout", type=float, default=1800)
    parser.add_argument("--poll", type=float, default=0.5)
    parser.add_argument("--require-download", action="store_true")
    parser.add_argument("--exercise-corpus", action="store_true")
    parser.add_argument("--source-root", type=Path)
    parser.add_argument("--output", type=Path, default=Path("work/model-startup.json"))
    args = parser.parse_args()
    if args.timeout <= 0 or args.poll <= 0:
        parser.error("timeout and poll must be positive")
    from scripts.evaluate_team_pdf import validate_report_destination

    validate_report_destination(
        args.output,
        protected_files=[
            Path("submissions/week07/gold-queries.json"),
            Path("submissions/week07/gold-queries.freeze.json"),
            Path("submissions/week07/search-config-final.json"),
            Path(".env"), Path(".env.example"),
        ],
        source_directories=[Path("models"), Path("fixtures"), Path("tests/fixtures")]
        + ([args.source_root] if args.source_root else []),
    )
    report = capture(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"passed": report["passed"], "checks": report["checks"]}, indent=2))
    raise SystemExit(0 if report["passed"] else 1)


if __name__ == "__main__":
    main()
