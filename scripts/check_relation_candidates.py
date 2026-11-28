"""Re-measure the entity candidate counts recorded in the evidence file.

The claim under test is about bounding, not about accuracy: the raw rules
produce far more candidates than a person would want, dropping line-initial
single words removes the sentence openers, and ranking by mention count keeps
ten. Those three numbers are quoted in `sections/B.md` and on the slides, so
they are measured here rather than asserted.

A candidate is counted as a distinct (entity type, label) pair, because that
is what the bounded list contains - counting every mention instead would
report the same name many times over.

Usage (inside the api container):

    python scripts/check_relation_candidates.py /fixtures/*.pdf

Exits non-zero if a file listed in EXPECTED no longer produces the recorded
numbers, which is a signal to update the evidence file rather than to ignore
the failure.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from services.parsing.chunking import chunk_document
from services.parsing.pdf import extract_document
from services.parsing.relations import MAX_CANDIDATES, candidate_relations, find_mentions

# Measured on these three decks on 2026-10-15, and recorded in
# evidence/relation-candidates.md: (rule off, rule on, bounded list).
EXPECTED: dict[str, tuple[int, int, int]] = {
    "Week 5 — Lab.pdf": (47, 39, 10),
    "Week 4 — Data Persistence and Schema Design.pdf": (44, 38, 10),
    "Week 5 — APIs and Network Communication.pdf": (36, 33, 10),
}


def _distinct(mentions) -> set[tuple[str, str]]:
    return {(mention.entity_type, mention.normalized_label) for mention in mentions}


def _measure(path: Path) -> tuple[int, int, int, list[str]]:
    chunks = chunk_document(extract_document(path))

    without_rule = _distinct(find_mentions(chunks, skip_line_initial=False))
    with_rule = _distinct(find_mentions(chunks))
    bounded = candidate_relations(chunks, MAX_CANDIDATES)

    return (
        len(without_rule),
        len(with_rule),
        len(bounded),
        [candidate.label for candidate in bounded],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pdfs", nargs="+", help="PDF files to measure")
    args = parser.parse_args(argv)

    print("distinct (type, label) candidates per document")
    print(
        f"{'file':<40}{'line-initial':<14}{'kept':<8}{'bounded':<9}recorded"
    )
    print("-" * 82)

    failures: list[str] = []
    for name in args.pdfs:
        path = Path(name)
        without_rule, with_rule, bounded, labels = _measure(path)
        expected = EXPECTED.get(path.name)
        verdict = ""
        if expected is not None:
            verdict = "agrees" if expected == (without_rule, with_rule, bounded) else (
                f"MISMATCH, recorded {expected}"
            )
            if expected != (without_rule, with_rule, bounded):
                failures.append(path.name)
        print(
            f"{path.name[:38]:<40}{without_rule:<14}{with_rule:<8}{bounded:<9}"
            f"{verdict}"
        )
        print(f"    bounded list: {', '.join(labels)}")

    print()
    print(
        "line-initial = candidates with the line-initial rule disabled; "
        "kept = with it on; bounded = the ten that survive ranking"
    )

    if failures:
        print(f"FAIL: {', '.join(failures)} no longer match the recorded numbers")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
