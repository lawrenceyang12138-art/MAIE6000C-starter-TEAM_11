"""Collect the W7 scan evidence from a running stack.

Runs the first scan, waits for the queue to settle, repeats the scan, and
reports the numbers the evidence documents quote. It talks to the public API
only - never the database - so every figure is something a client could have
observed.

What it can and cannot prove:

- first scan: files, versions and per-stage counts;
- repeated scan: no new files, versions or jobs;
- originals: their SHA-256 before and after the run.

Changing a single file and reverting it cannot be exercised here: the compose
mount is read-only by design, so those two cases stay unit-level
(``tests/unit/test_scan_handler.py``) and must be described as such.

Usage:
    python scripts/w7_evidence_probe.py --base-url http://localhost:8000

Writes JSON to stdout unless ``--out`` is given; prints a Markdown summary
suitable for pasting into an evidence document.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx

SETTLED_STAGES = {"discovered", "extracting"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _hash_tree(root: Path) -> dict[str, str]:
    """SHA-256 of every file under root, keyed by its relative path."""
    digests: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digests[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return digests


def _get(client: httpx.Client, path: str) -> dict | list:
    response = client.get(path)
    response.raise_for_status()
    return response.json()


def _post(client: httpx.Client, path: str, payload: dict | None = None) -> dict:
    response = client.post(path, json=payload)
    if response.status_code >= 400:
        raise RuntimeError(f"POST {path} -> {response.status_code} {response.text}")
    return response.json()


def _wait_for_job(client: httpx.Client, job_id: int, timeout: float) -> dict:
    """Poll one job until it stops moving."""
    deadline = time.monotonic() + timeout
    job: dict = {}
    while time.monotonic() < deadline:
        job = _get(client, f"/jobs/{job_id}")
        if job["status"] in {"completed", "failed"}:
            return job
        time.sleep(1.0)
    raise TimeoutError(f"job {job_id} did not finish within {timeout:.0f}s: {job}")


def _wait_until_settled(client: httpx.Client, root_id: str, timeout: float) -> tuple[dict, bool]:
    """Wait until no current version is still discovered or extracting."""
    deadline = time.monotonic() + timeout
    root: dict = {}
    while time.monotonic() < deadline:
        root = _get(client, f"/roots/{root_id}")
        counts = root["file_counts"]
        pending = sum(counts[stage] for stage in SETTLED_STAGES)
        if counts["total"] > 0 and pending == 0:
            return root, True
        time.sleep(2.0)
    return root, False


def _files(client: httpx.Client, root_id: str) -> list[dict]:
    return _get(client, f"/files?root_id={root_id}")


def _tally(files: list[dict], key: str) -> dict[str, int]:
    tally: dict[str, int] = {}
    for item in files:
        value = item.get(key) or "unknown"
        tally[value] = tally.get(value, 0) + 1
    return dict(sorted(tally.items()))


def probe(base_url: str, mount_id: str, relative_path: str, timeout: float) -> dict:
    with httpx.Client(base_url=base_url, timeout=15.0) as client:
        started = _now()
        health = _get(client, "/health/ready")

        accepted = _post(
            client, "/roots", {"mount_id": mount_id, "relative_path": relative_path}
        )
        root_id, job_id = accepted["root_id"], accepted["job_id"]
        first_job = _wait_for_job(client, job_id, timeout)
        first_root, first_settled = _wait_until_settled(client, root_id, timeout)
        first_files = _files(client, root_id)

        time.sleep(1.0)
        rescanned = _post(client, f"/roots/{root_id}/scans")
        second_job = _wait_for_job(client, rescanned["job_id"], timeout)
        second_root, second_settled = _wait_until_settled(client, root_id, timeout)
        second_files = _files(client, root_id)

        return {
            "base_url": base_url,
            "started_at": started,
            "finished_at": _now(),
            "health": health,
            "request": {"mount_id": mount_id, "relative_path": relative_path},
            "first_scan": {
                "root_id": root_id,
                "job_id": job_id,
                "job_status": first_job["status"],
                "settled": first_settled,
                "file_counts": first_root["file_counts"],
                "files_reported": len(first_files),
                "by_version_status": _tally(first_files, "status"),
                "by_presence": _tally(first_files, "presence_status"),
                "by_error_code": _tally(
                    [item for item in first_files if item.get("error_code")], "error_code"
                ),
                "unsupported_or_failed": sorted(
                    f"{item['relative_path']} ({item.get('error_code') or 'no code'})"
                    for item in first_files
                    if item.get("status") in {"failed", "unsupported"}
                ),
            },
            "repeat_scan": {
                "job_id": rescanned["job_id"],
                "job_status": second_job["status"],
                "settled": second_settled,
                "file_counts": second_root["file_counts"],
                "files_reported": len(second_files),
                "new_files": len(second_files) - len(first_files),
                "counts_unchanged": first_root["file_counts"] == second_root["file_counts"],
            },
        }


def _markdown(result: dict, originals: dict) -> str:
    first = result["first_scan"]
    repeat = result["repeat_scan"]
    counts = first["file_counts"]
    lines = [
        "## Scan evidence",
        "",
        f"- base URL: `{result['base_url']}`",
        f"- mount: `{result['request']['mount_id']}` / `{result['request']['relative_path']}`",
        f"- run: {result['started_at']} -> {result['finished_at']}",
        f"- root: `{first['root_id']}`, first job `{first['job_id']}`",
        "",
        "### First scan",
        "",
        f"- files: {counts['total']} (API reported {first['files_reported']} rows)",
        f"- stages: {json.dumps(counts, ensure_ascii=False)}",
        f"- by version status: {json.dumps(first['by_version_status'], ensure_ascii=False)}",
        f"- by presence: {json.dumps(first['by_presence'], ensure_ascii=False)}",
        f"- settled before timeout: {first['settled']}",
    ]
    if first["unsupported_or_failed"]:
        lines.append("- failed/unsupported: " + ", ".join(first["unsupported_or_failed"]))
    lines += [
        "",
        "### Repeated scan",
        "",
        f"- job `{repeat['job_id']}`, status {repeat['job_status']}, settled: {repeat['settled']}",
        f"- new file rows: {repeat['new_files']}",
        f"- counts unchanged: {repeat['counts_unchanged']}",
        "",
        "### Originals",
        "",
        f"- files hashed: {originals['checked']}, changed: {originals['changed']}, "
        f"missing: {originals['missing']}",
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--mount", default="corpus")
    parser.add_argument("--path", default=".")
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument(
        "--originals",
        type=Path,
        default=Path("tests/fixtures"),
        help="Host copy of the mounted corpus, hashed before and after the run",
    )
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)

    before = _hash_tree(args.originals) if args.originals.is_dir() else {}
    result = probe(args.base_url, args.mount, args.path, args.timeout)
    after = _hash_tree(args.originals) if args.originals.is_dir() else {}

    changed = [name for name, digest in before.items() if after.get(name) != digest]
    missing = [name for name in before if name not in after]
    originals = {
        "root": str(args.originals),
        "checked": len(before),
        "changed": len(changed),
        "missing": len(missing),
        "changed_paths": changed,
    }
    result["originals"] = originals

    payload = json.dumps(result, indent=2, ensure_ascii=False)
    if args.out is not None:
        args.out.write_text(payload, encoding="utf-8")
        print(_markdown(result, originals))
        print(f"\nJSON written to {args.out}")
    else:
        print(_markdown(result, originals))
        print("\n```json")
        print(payload)
        print("```")
    return 0


if __name__ == "__main__":
    sys.exit(main())
