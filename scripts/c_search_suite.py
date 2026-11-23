"""Validate and stage the checked-in W13 search corpus; never rewrite a freeze."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path, PurePosixPath

from services.search.page_navigation import parse_page_intent

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "fixtures/search/w13-v1"
STAGING = REPO / "work/c-search-validation"


class SuiteError(ValueError):
    """Invalid frozen or staged input; callers must not continue to search."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise SuiteError(message)


def digest(path: Path) -> str:
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def clean_text(text: str) -> str:
    return " ".join(text.split())


def safe_path(base: Path, relative: str) -> Path:
    # The spec uses portable relative paths and exact case; aliases are not accepted.
    value = PurePosixPath(relative)
    require(
        value.parts
        and value.as_posix() == relative
        and all(part not in {"..", "/"} for part in value.parts)
        and bool(re.fullmatch(r"[a-zA-Z0-9._/-]+", relative)),
        "invalid corpus path",
    )
    path = base / value
    require(path.resolve().is_relative_to(base.resolve()), "corpus path escapes its base")
    return path


def load_suite(directory: Path = FIXTURE) -> dict:
    freeze = json.loads((directory / "freeze.json").read_bytes())
    manifest_raw = (directory / "manifest.json").read_bytes()
    queries_raw = (directory / "queries.json").read_bytes()
    require(freeze["schema"] == "team11-search-freeze-v1", "unknown freeze schema")
    require(
        hashlib.sha256(manifest_raw).hexdigest() == freeze["manifest_sha256"],
        "frozen manifest hash mismatch",
    )
    require(
        hashlib.sha256(queries_raw).hexdigest() == freeze["queries_sha256"],
        "frozen queries hash mismatch",
    )
    manifest, gold = json.loads(manifest_raw), json.loads(queries_raw)
    require(
        manifest["schema"] == "team11-search-corpus-v1"
        and gold["schema"] == "team11-search-gold-v1",
        "unknown input schema",
    )
    files = manifest["files"]
    by_path = {row["relative_path"]: row for row in files}
    require(len(files) == len(by_path) and files, "empty corpus or duplicate paths")
    for row in files:
        safe_path(REPO, row["fixture_path"])
        safe_path(STAGING, row["relative_path"])
        require(
            row["group"] in {"w7-compose", "topical"}
            and not row["relative_path"].startswith("load/"),
            "invalid source group",
        )
        ready = type(row["page_count"]) is int and row["page_count"] > 0
        require(
            (ready and row["status"] == "ready" and row["error_code"] is None)
            or (
                row["page_count"] is None
                and row["status"] == "unsupported"
                and bool(row["error_code"])
            ),
            "invalid manifest source outcome",
        )
    seen = set()
    for query in gold["queries"]:
        require(
            query["id"] not in seen and query["query"].strip() and query["expected"],
            "duplicate ID or empty gold entry",
        )
        seen.add(query["id"])
        kind = query["kind"]
        require(
            kind in {"source_smoke", "topical"} and query["language"] in {"en", "zh"},
            "unknown query group or language",
        )
        if kind == "topical":
            require(
                parse_page_intent(query["query"]).intent is None,
                "topical query contains a physical-page instruction",
            )
        for location in query["expected"]:
            row = by_path.get(location["path"])
            require(
                row is not None
                and row["group"] == ("w7-compose" if kind == "source_smoke" else "topical")
                and row["page_count"] is not None
                and type(location["page"]) is int
                and 1 <= location["page"] <= row["page_count"]
                and bool(clean_text(location["quote"])),
                "invalid expected source location",
            )
    require(seen, "no gold queries")
    return {
        "files": by_path,
        "queries": gold["queries"],
        "freeze": freeze,
        "freeze_sha256": digest(directory / "freeze.json"),
    }


def corpus_plan(suite: dict, load_copies: int = 0) -> dict:
    """Repeat only the topical documents at distinct paths for a load-only corpus."""
    require(0 <= load_copies <= 50, "load-copies must be in 0..50")
    plan = dict(suite["files"])
    for batch in range(1, load_copies + 1):
        for relative, row in suite["files"].items():
            if row["group"] == "topical":
                plan[f"load/batch-{batch:02}/{relative}"] = row
    return plan


def matches(path: Path, row: dict) -> bool:
    return (
        not path.is_symlink()
        and path.is_file()
        and path.stat().st_size == row["byte_size"]
        and digest(path) == row["sha256"]
    )


def check_originals(suite: dict) -> None:
    """Validate hashes, physical page counts and exact quotes with an independent reader."""
    import pymupdf

    checks: dict[str, list[dict]] = {}
    for query in suite["queries"]:
        for expected in query["expected"]:
            checks.setdefault(expected["path"], []).append(expected)
    for relative, row in suite["files"].items():
        path = safe_path(REPO, row["fixture_path"])
        require(matches(path, row), f"fixture bytes differ: {relative}")
        if row["page_count"] is None:
            continue
        with pymupdf.open(path) as pdf:
            require(len(pdf) == row["page_count"], f"source page count differs: {relative}")
            for expected in checks.get(relative, []):
                text = clean_text(pdf[expected["page"] - 1].get_text())
                require(
                    clean_text(expected["quote"]) in text,
                    f"expected quote not found: {relative} physical page {expected['page']}",
                )


def validate_stage(directory: Path, plan: dict) -> None:
    require(directory.is_dir() and not directory.is_symlink(), "missing staged corpus")
    paths = list(directory.rglob("*"))
    require(
        not any(
            path.is_symlink() or not path.resolve().is_relative_to(directory.resolve())
            for path in paths
        ),
        "staged corpus has a link or out-of-scope path",
    )
    actual = {path.relative_to(directory).as_posix() for path in paths if path.is_file()}
    require(actual == set(plan), "staged paths do not match the manifest")
    for relative, row in plan.items():
        require(matches(safe_path(directory, relative), row), f"staged bytes differ: {relative}")


def stage(directory: Path, plan: dict) -> None:
    require(
        STAGING.resolve() == STAGING
        and directory.resolve().parent == STAGING
        and not directory.is_symlink(),
        "stage only a direct child under work/c-search-validation",
    )
    if not directory.exists():
        directory.mkdir(parents=True)
        for relative, row in plan.items():
            source = safe_path(REPO, row["fixture_path"])
            target = safe_path(directory, relative)
            target.parent.mkdir(parents=True, exist_ok=True)
            with source.open("rb") as reader, target.open("xb") as writer:
                shutil.copyfileobj(reader, writer)
    validate_stage(directory, plan)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["check", "stage"])
    parser.add_argument("--corpus", default="quality", choices=["quality", "load"])
    parser.add_argument("--load-copies", type=int, default=0)
    args = parser.parse_args()
    try:
        require(
            (args.corpus == "load") == (args.load_copies > 0),
            "use --corpus load with a positive --load-copies count",
        )
        suite = load_suite()
        check_originals(suite)
        plan = corpus_plan(suite, args.load_copies)
        if args.action == "stage":
            stage(STAGING / args.corpus, plan)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print(
        json.dumps(
            {
                "files": len(plan),
                "queries": len(suite["queries"]),
                "freeze_sha256": suite["freeze_sha256"],
                "human_b_review": suite["freeze"]["human_b_review"],
            }
        )
    )


if __name__ == "__main__":
    main()
