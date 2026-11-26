"""Measure real local search on the dedicated PostgreSQL/API/Worker/AI stack.

The only write is a fresh synthetic root through the API in prepare/load.
Recovery waits for the ordinary Worker; it never calls an indexing command.
Quality scores are measurements, not an approval or preset release gate.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import median

import httpx
from sqlalchemy import create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from scripts.c_search_suite import (
    REPO,
    STAGING,
    SuiteError,
    check_originals,
    clean_text,
    corpus_plan,
    digest,
    load_suite,
    require,
    validate_stage,
)
from scripts.evaluate_team_pdf import git_state
from scripts.verify_w7 import identity_sets, is_settled, snapshot
from services.common.schemas import SearchResponse
from services.search.page_metadata import PAGE_METADATA_POLICY
from services.search.text import MODEL_ID, MODEL_REVISION, TOKEN_DIMENSIONS
from services.search.token_store import text_fingerprint

MOUNT = "c-validation"
DATABASE = "c_search_validation"
REPORTS = REPO / "work/c-search-validation-reports"
MODES = ("keyword", "semantic", "hybrid")
BASELINE_PHASES = {"finish": "prepare", "probe": "finish"}


def timings(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {
        "samples": len(ordered),
        "median_ms": round(median(ordered), 2),
        "p95_ms": round(ordered[math.ceil(0.95 * len(ordered)) - 1], 2),
        "max_ms": round(ordered[-1], 2),
    }


def evidence_matches(hit, row: dict, source: dict) -> bool:
    return all(
        (
            row.get("file_id") == hit.file_id,
            row.get("version_id") == hit.version_id,
            row.get("chunk_id") == hit.chunk_id,
            row.get("relative_path") == hit.file_path,
            row.get("page_number") == hit.page,
            row.get("ordinal") == hit.ordinal,
            isinstance(row.get("text"), str) and row["text"][:2000] == hit.text,
            row.get("content_sha256") == source["sha256"],
        )
    )


def score_rows(expected: list[dict], ranked: list[dict], cutoff: int) -> dict:
    """Distinguish file-only, exact-page, and exact supporting passage."""
    ranks: dict[str, int | None] = dict.fromkeys(("file", "page", "quote"))
    for rank, row in enumerate(ranked, 1):
        if not row["verified"]:
            continue
        for location in expected:
            if row["path"] != location["path"]:
                continue
            ranks["file"] = ranks["file"] or rank
            if row["page"] == location["page"]:
                ranks["page"] = ranks["page"] or rank
                if clean_text(location["quote"]) in clean_text(row["text"]):
                    ranks["quote"] = ranks["quote"] or rank
    return {
        "first_rank": ranks,
        **{f"{item}_hit": rank is not None and rank <= cutoff for item, rank in ranks.items()},
    }


def summarize_quality(rows: list[dict]) -> list[dict]:
    summary = []
    for group in ("source_smoke", "topical"):
        for mode in MODES:
            for language in ("all",) if group == "source_smoke" else ("all", "en", "zh"):
                subset = [
                    row
                    for row in rows
                    if row["kind"] == group
                    and row["mode"] == mode
                    and (language == "all" or row["language"] == language)
                ]
                if not subset:
                    continue
                summary.append(
                    {
                        "kind": group,
                        "mode": mode,
                        "language": language,
                        "cutoff": subset[0]["cutoff"],
                        "queries": len(subset),
                        **{
                            f"{item}_hits": sum(row[f"{item}_hit"] for row in subset)
                            for item in ("file", "page", "quote")
                        },
                    }
                )
    return summary


class Run:
    def __init__(self, args, client, engine, suite, report):
        self.args, self.client, self.engine = args, client, engine
        self.suite, self.report = suite, report
        self.corpus = "load" if args.phase == "load" else "quality"
        self.plan = corpus_plan(suite, args.load_copies)
        self.directory = STAGING / self.corpus

    def request(self, method, path, expected=200, **kwargs):
        response = self.client.request(method, path, **kwargs)
        require(response.status_code == expected, f"{method} {path}: HTTP {response.status_code}")
        return response.json()

    def preflight(self) -> dict:
        check_originals(self.suite)
        validate_stage(self.directory, self.plan)
        self.request("GET", "/health/ready")
        mounts = self.request("GET", "/mounts")
        require(
            len(mounts) == 1
            and mounts[0].get("mount_id") == MOUNT
            and mounts[0].get("read_only") is True
            and mounts[0].get("availability") == "available",
            "not the fixture-only API",
        )
        with self.engine.connect() as conn:
            versions = (
                conn.execute(
                    text("""SELECT current_database() AS database,
                current_setting('server_version') AS postgres,
                (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS pgvector,
                (SELECT version_num FROM alembic_version) AS alembic""")
                )
                .mappings()
                .one()
            )
        require(versions["database"] == DATABASE and versions["pgvector"], "not the fixture DB")
        self.report["database"] = dict(versions)
        return self.request("GET", "/setup")

    def root_id(self) -> str | None:
        with self.engine.connect() as conn:
            return conn.execute(
                text("""SELECT id FROM authorized_roots
                WHERE mount_id = :mount AND relative_path = :path"""),
                {"mount": MOUNT, "path": self.corpus},
            ).scalar_one_or_none()

    def start_import(self) -> str:
        require(self.root_id() is None, "fixture root already exists; use a fresh project/volume")
        root = self.request(
            "POST", "/roots", 202, json={"mount_id": MOUNT, "relative_path": self.corpus}
        )
        root_id = root["root_id"]
        require(
            root.get("status") == "pending" and self.root_id() == root_id,
            "API and validation DB do not share the authorized root",
        )
        self.report["root_id"] = root_id
        return root_id

    def wait_for_indexes(self, root_id: str, *, enriched: bool, started: float) -> dict:
        deadline = started + self.args.timeout
        expected_ready = sum(row["status"] == "ready" for row in self.plan.values())
        while time.monotonic() < deadline:
            state = snapshot(self.engine, root_id)
            if len(state["files"]) == len(state["versions"]) == len(self.plan) and is_settled(
                state
            ):
                versions = Counter(row["status"] for row in state["versions"])
                self.report["last_observation"] = {
                    "statuses": versions,
                    "chunks": len(state["chunks"]),
                    "token_indexes": len(state["token_indexes"]),
                    "jobs": Counter(row["status"] for row in state["jobs"]),
                }
                expected = "enriched" if enriched else "basic_ready"
                if versions[expected] == expected_ready:
                    self.report["pipeline_wall_seconds"] = round(time.monotonic() - started, 3)
                    return state
            time.sleep(min(0.5, max(0, deadline - time.monotonic())))
        raise SuiteError("timed out waiting for the expected Worker state")

    def validate_state(self, root_id: str, state: dict, *, enriched: bool) -> dict:
        files = {row["relative_path"]: row for row in state["files"]}
        versions = {row["id"]: row for row in state["versions"]}
        require(set(files) == set(self.plan), "indexed paths differ from the frozen plan")
        require(
            all(row["status"] == "completed" for row in state["jobs"]),
            "Worker reported a failed or live job",
        )
        for path, source in self.plan.items():
            file = files[path]
            version = versions[file["current_version_id"]]
            expected = (
                ("enriched" if enriched else "basic_ready")
                if source["status"] == "ready"
                else "unsupported"
            )
            require(
                file["presence_status"] == "present"
                and version["file_id"] == file["id"]
                and version["status"] == expected
                and version["error_code"] == source["error_code"]
                and version["content_sha256"] == source["sha256"]
                and version["byte_size"] == source["byte_size"],
                f"source outcome differs: {path}",
            )
        searchable = {
            files[path]["current_version_id"]: (path, source)
            for path, source in self.plan.items()
            if source["status"] == "ready"
        }
        # Every physical page of a ready fixture should yield at least one chunk.
        expected_pages = {
            (version_id, page)
            for version_id, (_, source) in searchable.items()
            for page in range(1, source["page_count"] + 1)
        }
        chunk_pages = {(row["version_id"], row["page_number"]) for row in state["chunks"]}
        if missing := expected_pages - chunk_pages:
            version_id, page = min(missing)
            path, _ = searchable[version_id]
            raise SuiteError(
                f"missing chunk for {path} physical page {page} ({len(missing)} missing)"
            )
        require(chunk_pages == expected_pages, "chunk references an unexpected version or page")

        identities = identity_sets(state)
        chunks = identities["chunks"]
        require(
            bool(chunks) and identities["keyword_indexes"] == chunks,
            "keywords do not cover all chunks",
        )
        require(
            identities["token_indexes"] == (chunks if enriched else []),
            "unexpected token matrix coverage",
        )
        # Check compatibility and full-source fingerprints once, outside polling.
        with self.engine.connect() as conn:
            tokens = (
                conn.execute(
                    text("""SELECT i.chunk_id, i.model_id, i.model_revision,
                i.token_dimensions, i.token_count, i.text_sha256,
                jsonb_array_length(i.token_vectors) AS matrix_rows
                FROM chunk_token_search_index i JOIN source_chunks c ON c.id = i.chunk_id
                JOIN files f ON f.current_version_id = c.version_id WHERE f.root_id = :root"""),
                    {"root": root_id},
                )
                .mappings()
                .all()
            )
            metadata = (
                conn.execute(
                    text("""SELECT m.version_id, m.content_sha256, m.byte_size,
                m.policy_revision, m.parser_revision, m.page_count, v.parser_revision AS parser
                FROM version_page_search_metadata m JOIN file_versions v ON v.id = m.version_id
                JOIN files f ON f.current_version_id = m.version_id WHERE f.root_id = :root"""),
                    {"root": root_id},
                )
                .mappings()
                .all()
            )
        fingerprints = {row["id"]: text_fingerprint(row["text"]) for row in state["chunks"]}
        require(
            sorted(row["chunk_id"] for row in tokens) == identities["token_indexes"]
            and all(
                row["model_id"] == MODEL_ID
                and row["model_revision"] == MODEL_REVISION
                and row["token_dimensions"] == TOKEN_DIMENSIONS
                and row["matrix_rows"] == row["token_count"] > 0
                and row["text_sha256"] == fingerprints[row["chunk_id"]]
                for row in tokens
            ),
            "incompatible token matrix",
        )
        require({row["version_id"] for row in metadata} == set(searchable), "PDF metadata coverage")
        for row in metadata:
            _, source = searchable[row["version_id"]]
            require(
                row["content_sha256"] == source["sha256"]
                and row["byte_size"] == source["byte_size"]
                and row["page_count"] == source["page_count"]
                and row["policy_revision"] == PAGE_METADATA_POLICY
                and row["parser_revision"] == row["parser"],
                "incompatible physical-page metadata",
            )
        self.report["counts"] = {
            "files": len(files),
            "versions": len(versions),
            "chunks": len(chunks),
            "jobs": len(state["jobs"]),
            "keyword_indexes": len(chunks),
            "token_indexes": len(tokens),
            "page_metadata": len(metadata),
            "token_vectors": sum(row["token_count"] for row in tokens),
        }
        self.report["source_identities"] = {
            key: identities[key]
            for key in (
                "files",
                "versions",
                "chunks",
                "keyword_indexes",
                "page_metadata",
            )
        }
        return files

    def search(self, root_id, query, mode, files, *, fallback=False, read_evidence=True):
        start = time.perf_counter()
        raw = self.request(
            "POST",
            "/search",
            json={
                "root_id": root_id,
                "mode": mode,
                "query": query["query"],
                "top_k": 3,
            },
        )
        elapsed = (time.perf_counter() - start) * 1000
        result = SearchResponse.model_validate(raw)
        self.report["last_search"] = {
            "query_id": query["id"],
            "mode": mode,
            "effective_mode": result.effective_mode,
            "degradation_reason": result.degradation_reason,
        }
        require(
            result.mode == mode
            and result.degraded is fallback
            and result.effective_mode == ("keyword" if fallback else mode)
            and (
                result.degradation_reason == "ai_unavailable"
                if fallback
                else result.degradation_reason is None
            ),
            "unexpected search mode or degradation",
        )
        require(
            len({item.file_id for item in result.results}) == len(result.results),
            "search returned duplicate files",
        )
        ranked = []
        for hit in result.results:
            current = files.get(hit.file_path)
            require(
                current is not None
                and hit.root_id == root_id
                and current["id"] == hit.file_id
                and current["current_version_id"] == hit.version_id,
                "not a current scoped result",
            )
            if read_evidence:
                evidence = self.request("GET", f"/evidence/{hit.chunk_id}")
                require(
                    evidence_matches(hit, evidence, self.plan[hit.file_path]),
                    "source evidence disagrees with search",
                )
                ranked.append(
                    {
                        "path": hit.file_path,
                        "page": hit.page,
                        "chunk_id": hit.chunk_id,
                        "text": evidence["text"],
                        "verified": True,
                    }
                )
        return ranked, elapsed

    def check_quality(self, root_id: str, files: dict) -> None:
        rows = []
        for query in self.suite["queries"]:
            for mode in ("keyword",) if query["kind"] == "source_smoke" else MODES:
                ranked, elapsed = self.search(root_id, query, mode, files)
                cutoff = 1 if query["kind"] == "source_smoke" else 3
                metrics = score_rows(query["expected"], ranked, cutoff)
                rows.append(
                    {
                        "query_id": query["id"],
                        "kind": query["kind"],
                        "language": query["language"],
                        "mode": mode,
                        "cutoff": cutoff,
                        "elapsed_ms": round(elapsed, 2),
                        "expected": query["expected"],
                        "returned": [{"path": x["path"], "page": x["page"]} for x in ranked],
                        **metrics,
                    }
                )
        self.report["quality_rows"] = rows
        self.report["quality_summary"] = summarize_quality(rows)
        require(
            all(row["quote_hit"] for row in rows if row["kind"] == "source_smoke"),
            "exact source-location smoke misses",
        )

    def execute(self, baseline: dict | None, before_restart: dict | None = None) -> None:
        setup = self.preflight()
        phase, stage = self.args.phase, self.args.probe_stage
        baseline_phase = BASELINE_PHASES.get(phase)
        if baseline_phase:
            require(
                baseline is not None
                and baseline["phase"] == baseline_phase
                and baseline["passed"] is True
                and baseline["freeze_sha256"] == self.suite["freeze_sha256"]
                and baseline["root_id"] is not None
                and baseline["root_id"] == self.root_id(),
                f"successful {baseline_phase} report must match the active root and freeze",
            )
        offline = phase == "prepare" or stage in {"before", "after"}
        if offline:
            require(
                setup["state"] == "unavailable" and not setup["ready"],
                "stop the AI service before the offline check",
            )
        elif baseline_phase:
            started = time.monotonic()
            while not setup["ready"] and time.monotonic() < started + self.args.timeout:
                require(setup["state"] != "error", "local model setup reported an error")
                time.sleep(0.5)
                setup = self.request("GET", "/setup")
            require(setup["ready"] and setup["model"] == MODEL_ID, "pinned model is not ready")
            self.report["model_ready_wait_seconds"] = round(time.monotonic() - started, 3)
        else:
            require(setup["ready"] and setup["model"] == MODEL_ID, "prewarm the pinned model first")
        self.report["setup_state"] = setup["state"]
        started = time.monotonic()
        root_id = baseline["root_id"] if baseline_phase else self.start_import()
        self.report["root_id"] = root_id
        state = self.wait_for_indexes(root_id, enriched=phase != "prepare", started=started)
        files = self.validate_state(root_id, state, enriched=phase != "prepare")
        if phase != "load":
            marker = next(row for row in self.suite["queries"] if row["kind"] == "source_smoke")
            self.report["recovery_probe"] = {}
            for mode in MODES:
                ranked, _ = self.search(
                    root_id, marker, mode, files, fallback=offline and mode != "keyword"
                )
                metrics = score_rows(marker["expected"], ranked, 1 if mode == "keyword" else 3)
                self.report["recovery_probe"][mode] = {
                    **self.report["last_search"],
                    **metrics,
                    "returned": [
                        {key: hit[key] for key in ("path", "page", "chunk_id")} for hit in ranked
                    ],
                }
                require(metrics["quote_hit"], f"{mode} did not return the verified probe evidence")
        if baseline_phase:
            require(
                baseline["source_identities"] == self.report["source_identities"],
                "canonical source IDs differ from the baseline",
            )
        if phase == "probe":
            require(baseline["counts"] == self.report["counts"], "index or job counts changed")
            if stage == "after":
                require(
                    before_restart is not None
                    and before_restart["passed"] is True
                    and before_restart["root_id"] == root_id
                    and before_restart["freeze_sha256"] == self.suite["freeze_sha256"],
                    "before-restart report is missing or outdated",
                )
                require(
                    before_restart["recovery_probe"] == self.report["recovery_probe"],
                    "offline marker search results changed after recreation",
                )
            elif stage == "restored":
                require(
                    baseline["recovery_probe"] == self.report["recovery_probe"],
                    "restored marker search results differ from finish",
                )
        if phase == "finish":
            self.check_quality(root_id, files)
        if phase in {"finish", "load"}:
            self.measure(root_id, files)
        validate_stage(self.directory, self.plan)
        check_originals(self.suite)
        self.report["sources_unchanged"] = True

    def measure(self, root_id: str, files: dict) -> None:
        prompts = [row for row in self.suite["queries"] if row["kind"] == "topical"]
        self.report["http_timings"] = {}
        for mode in MODES:
            _, first = self.search(root_id, prompts[0], mode, files, read_evidence=False)
            samples = [
                self.search(root_id, query, mode, files, read_evidence=False)[1]
                for _ in range(self.args.rounds)
                for query in prompts
            ]
            self.report["http_timings"][mode] = {
                "first_measured_ms": round(first, 2),
                **timings(samples),
            }
        with self.engine.connect() as conn:
            self.report["database_bytes_entire_fixture_db"] = conn.execute(
                text("SELECT pg_database_size(current_database())")
            ).scalar_one()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=["prepare", "finish", "load", "probe"])
    parser.add_argument("--run-id", default="w13-local")
    parser.add_argument(
        "--probe-stage",
        choices=("before", "after", "restored"),
        help="read-only restart check for the same root as finish",
    )
    parser.add_argument(
        "--api-port", type=int, default=int(os.getenv("C_VALIDATION_API_PORT", 18085))
    )
    parser.add_argument(
        "--db-port", type=int, default=int(os.getenv("C_VALIDATION_DB_PORT", 15485))
    )
    parser.add_argument("--timeout", type=float, default=900)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--load-copies", type=int, default=0)
    args = parser.parse_args(argv)
    if (
        not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_-]{0,60}", args.run_id)
        or not (1 <= args.api_port <= 65535 and 1 <= args.db_port <= 65535)
        or not (0 < args.timeout <= 7200 and 1 <= args.rounds <= 10)
        or not (0 <= args.load_copies <= 50)
        or (args.phase == "load") != (args.load_copies > 0)
    ):
        parser.error("invalid run ID, ports, timeout, rounds, or load copy count")
    if (args.phase == "probe") != (args.probe_stage is not None):
        parser.error("probe requires --probe-stage; other phases do not accept it")
    report_name = f"probe-{args.probe_stage}" if args.phase == "probe" else args.phase
    out = REPORTS / args.run_id / f"{report_name}.json"
    if REPORTS.resolve() != REPORTS or not out.resolve().is_relative_to(REPORTS) or out.exists():
        parser.error(
            "report exists or is outside the validation reports directory; use a new run ID"
        )
    base = f"http://127.0.0.1:{args.api_port}"
    engine = create_engine(
        f"postgresql+psycopg://postgres:postgres@127.0.0.1:{args.db_port}/{DATABASE}",
        connect_args={"connect_timeout": 5},
    )
    # All DB connections from the verifier are read-only. Application services write via the API.
    engine = engine.execution_options(isolation_level="REPEATABLE READ", postgresql_readonly=True)
    report = {
        "phase": args.phase,
        "started_at": datetime.now(UTC).isoformat(),
        "harness_git": git_state(),
        "harness_sha256": {
            "verify_c_search.py": digest(Path(__file__)),
            "c_search_suite.py": digest(REPO / "scripts/c_search_suite.py"),
        },
        "parameters": vars(args),
        "load_copies": args.load_copies,
        "rounds": args.rounds,
        "passed": False,
        "runtime_model": MODEL_ID,
        "profile": "no_page_navigation_in_reference_compose; topical_queries_have_no_intent",
        "limits": [
            "No manual review or quality gate",
            "Load copies measure scale, not relevance",
            "Wall time measures a serial local HTTP client, excluding evidence readback",
        ],
    }
    try:
        suite = load_suite()
        report.update(
            freeze_sha256=suite["freeze_sha256"],
            human_b_review=suite["freeze"]["human_b_review"],
            team_threshold=suite["freeze"]["team_threshold"],
        )
        baseline_phase = BASELINE_PHASES.get(args.phase)
        baseline = (
            json.loads(out.with_name(f"{baseline_phase}.json").read_bytes())
            if baseline_phase
            else None
        )
        before_restart = (
            json.loads(out.with_name("probe-before.json").read_bytes())
            if args.probe_stage == "after"
            else None
        )
        with httpx.Client(
            base_url=base, headers={"Origin": base}, timeout=20, trust_env=False
        ) as client:
            Run(args, client, engine, suite, report).execute(baseline, before_restart)
        report["passed"] = True
    except SuiteError as exc:
        report["error"] = str(exc)
    except (httpx.HTTPError, SQLAlchemyError, OSError, KeyError, ValueError, TypeError) as exc:
        report["error"] = type(exc).__name__
    finally:
        engine.dispose()
    report["finished_at"] = datetime.now(UTC).isoformat()
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("x", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=True)
        file.write("\n")
    print(
        json.dumps(
            {
                "passed": report["passed"],
                "counts": report.get("counts"),
                "error": report.get("error"),
                "report": str(out),
            }
        )
    )
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
