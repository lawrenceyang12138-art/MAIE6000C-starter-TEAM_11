"""Stage the frozen Role C mix for isolated Role D browser checks; no product run."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path
from xml.etree import ElementTree

REPO = Path(__file__).resolve().parents[3]
OUTPUT = REPO / "work/w13/mixed-fixture"
C_FIXTURE_COMMIT = "21fa87a1b0c1ae90ffdf7dd67b16203430ac945a"
C_FIXTURE_PATH = "fixtures/search/formats-v1"
MANIFEST_SHA256 = "d8a4408b1f0601ea8dffbfaba8c9340fd02fb564af1b9051b8dd19058c9b6a0d"
FORMATS = ("pdf", "txt", "md", "docx")
WORD = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def git_blob(name: str) -> bytes:
    return subprocess.run(
        ["git", "show", f"{C_FIXTURE_COMMIT}:{C_FIXTURE_PATH}/{name}"],
        cwd=REPO, capture_output=True, check=True, timeout=15,
    ).stdout


def read_original(fmt: str, raw: bytes) -> dict[int | None, str]:
    """Decode fixtures independently of the product and preserve native whitespace."""
    if fmt == "pdf":
        try:
            import pymupdf
        except ImportError:
            import pdfplumber

            with pdfplumber.open(io.BytesIO(raw)) as document:
                return {
                    index: page.extract_text() or "" for index, page in enumerate(document.pages, 1)
                }
        with pymupdf.open(stream=raw, filetype="pdf") as document:
            return {index: page.get_text() for index, page in enumerate(document, 1)}

    if fmt == "docx":
        with zipfile.ZipFile(io.BytesIO(raw)) as document:
            root = ElementTree.fromstring(document.read("word/document.xml"))
        paragraphs = []
        for paragraph in root.findall(f"./{WORD}body/{WORD}p"):
            pieces = []
            for node in paragraph.iter():
                if node.tag == f"{WORD}t":
                    pieces.append(node.text or "")
                elif node.tag == f"{WORD}br":
                    pieces.append("\n")
                elif node.tag == f"{WORD}tab":
                    pieces.append("\t")
            paragraphs.append("".join(pieces))
        decoded = "\n".join(paragraphs)
    else:
        decoded = raw.decode("utf-8-sig", errors="strict")
    return {None: decoded.replace("\r\n", "\n").replace("\r", "\n")}


def rejected_code(fmt: str, raw: bytes) -> str:
    if fmt == "txt":
        try:
            raw.decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError:
            return "invalid_encoding"
    if fmt == "md" and not raw.decode("utf-8-sig", errors="strict").strip():
        return "empty_text"
    if fmt == "docx" and not zipfile.is_zipfile(io.BytesIO(raw)):
        return "docx_corrupt"
    if fmt == "pdf" and raw.startswith(b"%PDF-") and b"%%EOF" not in raw:
        return "corrupt"
    raise ValueError(f"Frozen {fmt} failure fixture no longer matches its defect")


def collect() -> tuple[dict, dict[str, bytes], list[dict], list[dict]]:
    frozen = git_blob("manifest.json")
    require(sha256(frozen) == MANIFEST_SHA256, "Frozen manifest digest changed")
    gold = json.loads(frozen)
    archive_bytes = git_blob("sources.zip")
    require(sha256(archive_bytes) == gold["archive_sha256"], "Frozen archive digest changed")
    expected_paths = {
        f"{fmt}/{stem}.{fmt}" for fmt in FORMATS for stem in ("01-en", "02-bad", "03-zh")
    }
    rows = {row["path"]: row for row in gold["files"]}
    require(set(rows) == expected_paths and len(gold["files"]) == 12, "Unexpected source list")
    originals, contents, sources, extra_queries = {}, {}, [], []
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        require(sorted(archive.namelist()) == sorted(expected_paths), "Unexpected ZIP members")
        for path, row in sorted(rows.items()):
            fmt = path.split("/")[0]
            require(archive.getinfo(path).file_size == row["byte_size"], f"Wrong ZIP size: {path}")
            raw = contents[path] = archive.read(path)
            require(len(raw) == row["byte_size"] and sha256(raw) == row["sha256"],
                    f"Wrong source bytes: {path}")
            source = dict(path=path, sha256=row["sha256"], byte_size=len(raw), format=fmt,
                          fixture_path=(OUTPUT / "sources" / path).relative_to(REPO).as_posix())
            if row["kind"] == "negative":
                code = rejected_code(fmt, raw)
                require("/02-bad." in path and code in row["expected_errors"],
                        f"Wrong rejection expectation: {path}")
                sources.append(dict(source, status="unsupported", error_code=code,
                                    defect=row["defect"]))
                continue
            pages = originals[path] = read_original(fmt, raw)
            physical_page_count = len(pages) if fmt == "pdf" else None
            require(row["page_count"] == physical_page_count and
                    path.endswith(f'-{row["language"]}.{fmt}'), f"Wrong location metadata: {path}")
            populated = [page for page, value in pages.items() if value.strip()]
            require({q["page"] for q in row["queries"]} == set(populated),
                    f"Missing or imaginary page: {path}")
            # Every non-empty page/body here is well under one chunk's normal 700 chars.
            for index, query in enumerate(row["queries"]):
                page = query["page"]
                original = pages[page]
                contains_quote = (" ".join(query["quote"].split()) in " ".join(original.split())
                                  if fmt == "pdf" else query["quote"] in original)
                require(len(original) < 500 and query["keyword"] in query["quote"]
                        and contains_quote, f"Wrong independently read passage: {path}")
                expected = dict(query=query["keyword"], page=page,
                                ordinal=populated.index(page) + 1, lang=row["language"],
                                text=query["quote"] if fmt == "pdf" else original,
                                exact_text=fmt != "pdf")
                if index == 0:
                    sources.append(dict(source, status="basic_ready", **expected))
                else:
                    extra_queries.append(dict(path=path, **expected))
    queries = [row for row in sources if "query" in row] + extra_queries
    require(len(queries) == 10, "Wrong positive query count")
    for row in queries:
        matches = [
            (path, page) for path, pages in originals.items() for page, value in pages.items()
            if row["query"] in value
        ]
        require(matches == [(row["path"], row["page"])], f'Query was not unique: {row["query"]}')
    require(not any(gold["absent_keyword"] in value for pages in originals.values()
                    for value in pages.values()), "Absent keyword occurs in a fixture")
    return gold, contents, sources, extra_queries


def write_new_or_same(path: Path, raw: bytes) -> None:
    # Refuse to follow a redirection or overwrite a previous run's input.
    require(path.resolve() == path, f"Redirected output path: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as output:
            output.write(raw)
    except FileExistsError:
        require(path.is_file() and path.read_bytes() == raw, f"Different output exists: {path}")


def compose_override(source_root: Path) -> bytes:
    relative_mounts = json.dumps({"corpus": "/source/corpus", "w13-mixed": "/source/w13-mixed"})
    return f"""# Local synthetic-sources-only browser test overlay (keeps the base corpus).
services:
  api:
    environment: &w13_environment
      SOURCE_MOUNTS: '{relative_mounts}'
      EMBEDDING_ENABLED: 'false'
      EMBEDDING_AUTO_PREPARE: 'false'
    volumes:
      - &w13_source
        type: bind
        source: {json.dumps(source_root.as_posix(), ensure_ascii=False)}
        target: /source/w13-mixed
        read_only: true
        bind:
          create_host_path: false
  worker:
    environment: *w13_environment
    volumes:
      - *w13_source
""".encode("utf-8")


def stage(gold: dict, contents: dict[str, bytes], sources: list[dict], extras: list[dict]) -> None:
    source_root = OUTPUT / "sources"
    require(source_root.resolve() == source_root, "Source staging is redirected")
    existing = {p.relative_to(source_root).as_posix() for p in source_root.rglob("*")
                if p.is_file() or p.is_symlink()}
    require(existing <= set(contents), "Unexpected file in staging; nothing was removed")
    for path, raw in contents.items():
        write_new_or_same(source_root / path, raw)

    def profile(text: bool, docx: bool) -> dict:
        enabled = {"pdf"}
        if text:
            enabled.update(("txt", "md"))
        if docx:
            enabled.add("docx")
        registry = []
        for row in sources:
            if row["format"] in enabled:
                registry.append(row)
            else:
                excluded = {"query", "text", "page", "ordinal", "lang", "exact_text", "defect"}
                disabled = {key: value for key, value in row.items() if key not in excluded}
                registry.append(dict(disabled, status="unsupported",
                                     error_code="unsupported_format"))
        return dict(suite=gold["suite"], kind="frozen fixture expectations only",
                    source_commit=C_FIXTURE_COMMIT, frozen_manifest_sha256=MANIFEST_SHA256,
                    archive_sha256=gold["archive_sha256"], mount_id="w13-mixed", relative_path=".",
                    expected_flags={"TEXT_PARSING_ENABLED": text, "DOCX_PARSING_ENABLED": docx},
                    absent_keyword=gold["absent_keyword"], sources=registry, queries=extras)

    for name, text, docx in (("browser-manifest.json", True, True),
                             ("browser-manifest.pdf-only.json", False, False)):
        manifest = (json.dumps(profile(text, docx), ensure_ascii=False, indent=2) + "\n")
        write_new_or_same(OUTPUT / name, manifest.encode("utf-8"))
    write_new_or_same(OUTPUT / "compose.mixed.override.yaml", compose_override(source_root))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("check", "stage"), default="check", nargs="?")
    args = parser.parse_args()
    gold, contents, sources, extras = collect()
    if args.action == "stage":
        stage(gold, contents, sources, extras)
    print(json.dumps(dict(files=len(contents), positive_queries=10, runtime="UNVERIFIED",
                          fixture_commit=C_FIXTURE_COMMIT, frozen_manifest_sha256=MANIFEST_SHA256,
                          staged_to=str(OUTPUT) if args.action == "stage" else None)))


if __name__ == "__main__":
    main()
