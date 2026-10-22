"""Check frozen answers against actual PDF text, not the mock evidence strings.

Requires pypdf. This verifies source locations only, not retrieval/model quality
or a human review. It never updates the gold file or its freeze hashes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path

from pypdf import PdfReader

REPO = Path(__file__).resolve().parents[1]
GOLD = REPO / "submissions/week07/gold-queries.json"
FREEZE = REPO / "submissions/week07/gold-queries.freeze.json"

# Every check in this module is an assert. Under python -O those vanish and the
# script would report success without verifying anything, so refuse to run.
if not __debug__:  # pragma: no cover - defensive
    raise SystemExit("validate_d_gold.py relies on assert; do not run it with -O")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate() -> dict:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    assert digest(GOLD) == freeze["gold_sha256"], "Frozen answers changed"
    manifest_path = REPO / "fixtures/manifest.json"
    assert digest(manifest_path) == freeze["manifest_sha256"], "Frozen corpus changed"
    gold = json.loads(GOLD.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    records = {record["file_id"]: record for record in manifest["files"]}
    queries = gold["queries"]
    assert len(queries) == 10
    assert len({query["query_id"] for query in queries}) == 10
    assert sum(query["kind"] == "keyword" for query in queries) == 5
    assert sum(query["kind"] == "semantic_description" for query in queries) == 5
    assert {query["language"] for query in queries} == {"en", "zh"}
    # Validate every corpus hash, including abnormal/unsupported records.
    for record in manifest["files"]:
        source = (REPO / "fixtures" / record["relative_path"]).resolve()
        assert source.is_relative_to(REPO / "fixtures")
        assert digest(source) == record["sha256"], record["relative_path"]
    locations = []
    no_keyword_count = 0
    folders = set()
    for query in queries:
        assert query["query"].strip() and query["expected"]
        for expected in query["expected"]:
            record = records[expected["file_id"]]
            assert record["expected_status"] == "basic_ready"
            assert expected["version_id"] == record["version_id"]
            assert expected["relative_path"] == record["relative_path"]
            page = expected["page"]
            assert type(page) is int and 1 <= page <= record["page_count"]
            source = REPO / "fixtures" / record["relative_path"]
            reader = PdfReader(source)
            assert len(reader.pages) == record["page_count"]
            text = reader.pages[page - 1].extract_text()
            assert expected["excerpt"] in text, query["query_id"]
            if query.get("avoids_source_keywords"):
                source_words = set(re.findall(r"[a-z]+", text.lower()))
                query_words = set(re.findall(r"[a-z]+", query["query"].lower()))
                assert not source_words.intersection(query_words), query["query_id"]
                no_keyword_count += 1
            folders.add(str(Path(record["relative_path"]).parent))
            locations.append(
                {
                    "query_id": query["query_id"],
                    "file_id": record["file_id"],
                    "page": page,
                }
            )
    assert no_keyword_count >= 2
    assert len(folders) >= 2
    return {
        "status": "passed_source_location_checks",
        "queries": len(queries),
        "keyword": 5,
        "semantic_descriptions": 5,
        "no_source_keyword_descriptions": no_keyword_count,
        "pdf_locations_verified": len(locations),
        "corpus_files_hash_verified": len(records),
        "gold_sha256": digest(GOLD),
        "human_B_review": gold["human_review"]["status"],
        "retrieval_evaluation": "not_run",
        "limitations": "The corpus has numbered placeholder text, not realistic topical content.",
        "locations": locations,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--report",
        type=Path,
        help="Optional JSON evidence output within this repo",
    )
    args = parser.parse_args()
    output = json.dumps(validate(), ensure_ascii=False, indent=2)
    if args.report:
        report_path = args.report.resolve()
        if not report_path.is_relative_to(REPO):
            parser.error("Report path must be within this repository")
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(output + "\n", encoding="utf-8")
    print(output)
