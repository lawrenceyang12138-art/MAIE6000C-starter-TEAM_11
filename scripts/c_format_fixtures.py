"""Check original source bytes and stage only the synthetic mixed-format corpus."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from io import BytesIO
from xml.etree import ElementTree
from zipfile import ZipFile

from scripts.c_search_suite import REPO, digest, require, safe_path, validate_stage

SUITE = REPO / "fixtures/search/formats-v1"
STAGE = REPO / "work/c-format-validation/sources"
FORMATS = ("txt", "md", "docx", "pdf")


def read_original(fmt: str, raw: bytes) -> dict:
    """Physical PDF pages, but no fabricated page for text, Markdown or Word."""
    if fmt == "pdf":
        import pymupdf

        with pymupdf.open(stream=raw, filetype="pdf") as pdf:
            return {i: page.get_text() for i, page in enumerate(pdf, 1)}
    if fmt == "docx":
        ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
        with ZipFile(BytesIO(raw)) as doc:
            body = ElementTree.fromstring(doc.read("word/document.xml"))
        w = "{" + ns["w"] + "}"
        def paragraph(p):
            return "".join(n.text or "" if n.tag == w + "t" else
                           "\n" if n.tag == w + "br" else "\t" if n.tag == w + "tab" else ""
                           for n in p.iter())
        return {None: "\n".join(paragraph(p) for p in body.findall(".//w:body/w:p", ns))}
    return {None: raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n")}


def passage(text: str, fmt: str) -> str:
    if fmt == "pdf":
        return " ".join(text.split())  # PDF layout whitespace is reader-dependent.
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Paragraph separators in OOXML are structural. Never remove indentation or join words.
    return re.sub(r"\n{2,}", "\n", text) if fmt == "docx" else text


def load():
    require(digest(SUITE / "manifest.json") == (SUITE / "manifest.sha256").read_text().strip(),
            "expected answers changed")
    gold = json.loads((SUITE / "manifest.json").read_bytes())
    plan = {row["path"]: row for row in gold["files"]}
    expected = {f"{fmt}/{stem}.{fmt}" for fmt in FORMATS for stem in ("01-en", "02-bad", "03-zh")}
    require(set(plan) == expected and len(gold["files"]) == len(expected), "unexpected corpus")
    require(digest(SUITE / "sources.zip") == gold["archive_sha256"], "source archive changed")
    originals, contents = {}, {}
    with ZipFile(SUITE / "sources.zip") as archive:
        require(sorted(archive.namelist()) == sorted(plan), "archive inventory changed")
        for path, row in plan.items():
            raw = contents[path] = archive.read(path)
            require(len(raw) == row["byte_size"] and hashlib.sha256(raw).hexdigest()
                    == row["sha256"], f"source bytes changed: {path}")
            if "02-bad" in path:
                require(row["kind"] == "negative" and bool(row["defect"]), path)
                continue
            fmt = path.split("/")[0]
            require(row["kind"] == "positive" and path.endswith(f'-{row["language"]}.{fmt}'), path)
            pages = originals[path] = read_original(fmt, raw)
            require((len(pages) if fmt == "pdf" else None) == row["page_count"], path)
            require({q["page"] for q in row["queries"]} == {p for p, t in pages.items()
                    if t.strip()}, f"missing or fictional source page: {path}")
    for path, pages in originals.items():
        for q in plan[path]["queries"]:
            locations = [(p, n) for p, texts in originals.items() for n, txt in texts.items()
                         if q["keyword"] in txt]
            require(locations == [(path, q["page"])] and q["keyword"] in q["quote"]
                    and q["quote"] in pages[q["page"]], f"wrong source/quote: {path}")
    require(not any(gold["absent_keyword"] in t for p in originals.values() for t in p.values()),
            "negative keyword occurs in a source")
    return gold, plan, originals, contents


def stage(plan, contents):
    require(STAGE.resolve() == STAGE, "staging path must not be redirected")
    if not STAGE.exists():
        STAGE.mkdir(parents=True)
        for relative, raw in contents.items():
            dest = safe_path(STAGE, relative)
            dest.parent.mkdir(exist_ok=True)
            with dest.open("xb") as f:
                f.write(raw)
    # Existing or extra files are never silently replaced or removed.
    validate_stage(STAGE, plan)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "stage"))
    args = parser.parse_args()
    gold, plan, _, contents = load()
    if args.action == "stage":
        stage(plan, contents)
    print(json.dumps({"files": len(plan), "positive_queries": sum(len(r.get("queries", []))
                      for r in plan.values()), "manifest_sha256": digest(SUITE / "manifest.json"),
                      "archive_sha256": gold["archive_sha256"], "runtime": "UNVERIFIED"}))


if __name__ == "__main__":
    main()
