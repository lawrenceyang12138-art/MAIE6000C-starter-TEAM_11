"""Check the W7 submission files without starting the application stack."""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUBMISSION = ROOT / "submissions" / "week07"


def words(path: Path) -> int:
    text = path.read_text(encoding="utf-8")
    return len(re.findall(r"\S+", text))


def qa_count(path: Path) -> int:
    return len(re.findall(r"^## Q\d+\.", path.read_text(encoding="utf-8"), flags=re.MULTILINE))


def step_count(path: Path) -> int:
    return len(
        re.findall(r"^## Step \d+\b", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    )


def pptx_slides(path: Path) -> int:
    with zipfile.ZipFile(path) as archive:
        presentation = archive.read("ppt/presentation.xml").decode("utf-8")
    return len(re.findall(r"<p:sldId\b", presentation))


def pdf_pages(path: Path) -> int:
    try:
        from pypdf import PdfReader

        return len(PdfReader(str(path)).pages)
    except ImportError:
        # The Docker image always has pypdf. Regex is a conservative fallback
        # for a local shell without the project dependencies.
        text = path.read_bytes().decode("latin-1")
        return len(re.findall(r"/Type\s*/Page\b", text))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def manifest_hashes(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8")
    return {
        name: digest
        for name, digest in re.findall(
            r"\|\s*`([^`]+)`\s*\|\s*`([0-9a-f]{64})`\s*\|",
            text,
        )
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail when recording, second-computer or local model evidence is missing.",
    )
    args = parser.parse_args()

    hard_failures: list[str] = []
    pending: list[str] = []

    required = [
        "README.md",
        "report.md",
        "demo-script.md",
        "qa.md",
        "sections/A.md",
        "sections/B.md",
        "sections/C.md",
        "sections/D.md",
        "W07_Team11.pptx",
        "W07_Team11.pdf",
        "release-manifest-final.md",
        "evidence/m1-browser-2026-10-17.md",
    ]
    for relative in required:
        path = SUBMISSION / relative
        if not path.is_file():
            hard_failures.append(f"missing {relative}")

    word_requirements = {
        "report.md": 3000,
        "sections/A.md": 700,
        "sections/B.md": 700,
        "sections/C.md": 700,
        "sections/D.md": 900,
        "demo-script.md": 600,
    }
    for relative, minimum in word_requirements.items():
        path = SUBMISSION / relative
        if path.is_file():
            count = words(path)
            print(f"{relative}: {count} words (minimum {minimum})")
            if count < minimum:
                hard_failures.append(f"{relative} has {count} words, needs {minimum}")

    qa_path = SUBMISSION / "qa.md"
    if qa_path.is_file():
        count = qa_count(qa_path)
        print(f"qa.md: {count} questions (minimum 8)")
        if count < 8:
            hard_failures.append(f"qa.md has {count} questions, needs 8")

    demo_path = SUBMISSION / "demo-script.md"
    if demo_path.is_file():
        count = step_count(demo_path)
        print(f"demo-script.md: {count} steps (expected 6)")
        if count != 6:
            hard_failures.append(f"demo-script.md has {count} steps, expected 6")

    pptx_path = SUBMISSION / "W07_Team11.pptx"
    if pptx_path.is_file():
        count = pptx_slides(pptx_path)
        print(f"W07_Team11.pptx: {count} slides (expected 12)")
        if count != 12:
            hard_failures.append(f"W07_Team11.pptx has {count} slides, expected 12")

    pdf_path = SUBMISSION / "W07_Team11.pdf"
    if pdf_path.is_file():
        count = pdf_pages(pdf_path)
        print(f"W07_Team11.pdf: {count} pages (expected 12)")
        if count != 12:
            hard_failures.append(f"W07_Team11.pdf has {count} pages, expected 12")

    manifest_path = SUBMISSION / "release-manifest-final.md"
    if manifest_path.is_file():
        declared = manifest_hashes(manifest_path)
        for name, expected in declared.items():
            path = SUBMISSION / name
            if not path.is_file():
                continue
            actual = sha256(path)
            print(f"{name}: sha256 {'matches' if actual == expected else 'MISMATCH'}")
            if actual != expected:
                hard_failures.append(f"{name} hash differs from release manifest")

    corpus = ROOT / "fixtures" / "demo-corpus"
    normal = list((corpus / "normal").rglob("*.pdf"))
    abnormal = list((corpus / "abnormal").glob("*.pdf"))
    unsupported = list((corpus / "unsupported").glob("*"))
    print(f"corpus: normal={len(normal)}, abnormal={len(abnormal)}, unsupported={len(unsupported)}")
    if (len(normal), len(abnormal), len(unsupported)) != (12, 3, 1):
        hard_failures.append("demo corpus does not match 12 normal / 3 abnormal / 1 unsupported")

    if not (SUBMISSION / "demo-backup.mp4").is_file():
        pending.append("demo-backup.mp4 is not recorded")
    if not list(SUBMISSION.glob("*second*computer*")):
        pending.append("second-computer install record is not present")
    if not (ROOT / "models" / "multilingual-e5-small").is_dir():
        pending.append("local E5 model bundle is not present; semantic quality is unverified")

    print("\nHard check:", "PASS" if not hard_failures else "FAIL")
    for failure in hard_failures:
        print("  FAIL:", failure)
    for item in pending:
        print("  PENDING:", item)
    if hard_failures or (args.strict and pending):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
