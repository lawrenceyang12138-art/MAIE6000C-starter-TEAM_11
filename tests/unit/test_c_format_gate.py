"""Adversarial checks of the verifier itself; none are candidate acceptance evidence."""

import json
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
from zipfile import is_zipfile

import httpx
import pytest

from scripts import c_format_fixtures as fixtures
from scripts import verify_c_formats as gate
from scripts.c_format_stack import read_flags
from scripts.c_search_suite import SuiteError


@pytest.fixture(scope="module")
def suite():
    return fixtures.load()


def test_sources_are_bilingual_with_page_gap_and_negative_controls(suite):
    _, plan, sources, raw = suite
    for fmt in fixtures.FORMATS:
        en, zh = (f"{fmt}/{n}.{fmt}" for n in ("01-en", "03-zh"))
        assert plan[en]["language"] == "en" and plan[zh]["language"] == "zh"
        assert any("\u4e00" <= ch <= "\u9fff" for ch in plan[zh]["queries"][0]["keyword"])
        assert plan[f"{fmt}/02-bad.{fmt}"]["expected_errors"]
        if fmt != "pdf":
            assert set(sources[en]) == set(sources[zh]) == {None}
    assert list(sources["pdf/01-en.pdf"]) == [1, 2, 3]
    assert not sources["pdf/01-en.pdf"][2].strip()
    assert sum(len(r.get("queries", [])) for r in plan.values()) == 10
    with pytest.raises(UnicodeDecodeError):
        raw["txt/02-bad.txt"].decode("utf-8")
    assert not raw["md/02-bad.md"].strip()
    assert not is_zipfile(BytesIO(raw["docx/02-bad.docx"]))
    assert raw["pdf/02-bad.pdf"] == b"%PDF-1.4\n"
    assert raw["txt/03-zh.txt"].startswith(b"\xef\xbb\xbf")
    assert "north-\ncobaltspindle" in sources["txt/01-en.txt"][None]
    assert "\n    retain" in sources["md/01-en.md"][None]
    assert "reads\njadesprocket" in sources["docx/01-en.docx"][None]


def test_stage_does_not_replace_modified_or_extra_files(suite, tmp_path, monkeypatch):
    _, plan, _, raw = suite
    target = tmp_path / "sources"
    monkeypatch.setattr(fixtures, "STAGE", target)
    fixtures.stage(plan, raw)
    extra = target / "unrelated.txt"
    extra.write_bytes(b"leave this alone")
    with pytest.raises(SuiteError, match="paths"):
        fixtures.stage(plan, raw)
    assert extra.read_bytes() == b"leave this alone"
    extra.unlink()
    changed = target / "txt/01-en.txt"
    changed.write_bytes(b"different")
    with pytest.raises(SuiteError, match="bytes"):
        fixtures.stage(plan, raw)
    assert changed.read_bytes() == b"different"


def test_flags_require_A_scope_and_never_accept_db_override(tmp_path):
    flags = tmp_path / "candidate.env"
    flags.write_text("TEXT_PARSING_ENABLED=true\nDOCX_PARSING_ENABLED=false\n")
    assert read_flags(flags, {"txt", "md"})["DOCX_PARSING_ENABLED"] == "false"
    with pytest.raises(SuiteError, match="disabled"):
        read_flags(flags, {"docx"})
    with flags.open("a") as f:
        f.write("DATABASE_URL=anything\n")
    with pytest.raises(SuiteError, match="unknown"):
        read_flags(flags, {"txt"})


def test_rescan_must_not_hide_duplicate_versions_behind_a_stable_current_pointer():
    state = {"files": [{"relative_path": "a", "id": "f", "current_version_id": "v"}],
             "versions": [{"file_id": "f", "id": "v"}]}
    gate.source_state(state, "a")
    state["versions"].append({"file_id": "f", "id": "v2"})
    with pytest.raises(SuiteError, match="duplicate"):
        gate.source_state(state, "a")


@pytest.fixture
def example(suite):
    _, plan, sources, _ = suite
    path = "txt/03-zh.txt"
    row = plan[path]
    q = row["queries"][0]
    file = {"id": "f", "relative_path": path, "current_version_id": "v",
            "presence_status": "present"}
    version = {"id": "v", "file_id": "f", "content_sha256": row["sha256"], "status": "basic_ready",
               "error_code": None, "byte_size": row["byte_size"]}
    chunk = {"id": "c", "version_id": "v", "ordinal": 1, "page_number": None, "text": q["quote"]}
    state = {"files": [file], "versions": [version], "chunks": [chunk], "pdf_metadata": [],
             "keyword_indexes": [{"chunk_id": "c"}], "jobs": [{"job_type": "extract_file",
             "version_id": "v", "attempts": 1, "status": "completed"}], "page_probe": {
             "active": True, "diagnostics": {"files": []}, "pdf_metadata_lookups": {},
             "chunks": {"v": [{"id": "c",
                                                                          "allowed": True}]}}}
    hit = {"file_id": "f", "version_id": "v", "chunk_id": "c", "file_path": path, "ordinal": 1,
           "page": None, "text": q["quote"], "root_id": "root", "reason": "keyword"}
    ev = {"file_id": "f", "version_id": "v", "chunk_id": "c", "relative_path": path,
          "ordinal": 1, "page_number": None, "text": q["quote"], "content_sha256": row["sha256"]}
    listing = {path: {"file_id": "f", "root_id": "root", "version_id": "v", "status": "basic_ready",
                      "error_code": None, "presence_status": "present"}}
    return SimpleNamespace(path=path, row=row, q=q, file=file, version=version, chunk=chunk,
                           state=state, hit=hit, ev=ev, listing=listing, sources=sources)


@pytest.mark.parametrize("key,value", [("version_id", "old"), ("file_id", "neighbor"),
                         ("chunk_id", "other"), ("content_sha256", "wrong"), ("ordinal", 2),
                         ("page_number", 1), ("text", "not source text")])
def test_evidence_disagreement_is_not_a_pass(example, key, value):
    e = example
    ev = dict(e.ev, **{key: value})
    with pytest.raises(SuiteError, match="evidence differs"):
        gate.verify_hit(e.hit, ev, "root", e.file, e.version, {"c": e.chunk},
                        e.sources[e.path], e.q, "txt")


def test_consistently_wrong_text_is_caught_against_original(example):
    e = example
    for item in (e.ev, e.hit, e.chunk):
        item["text"] += " made up"
    with pytest.raises(SuiteError, match="original source"):
        gate.verify_hit(e.hit, e.ev, "root", e.file, e.version, {"c": e.chunk},
                        e.sources[e.path], e.q, "txt")


def test_paging_probe_and_unfiltered_keyword_request(example):
    e = example
    result = {"mode": "keyword", "effective_mode": "keyword", "degraded": False, "results": [e.hit]}
    def response(req):
        return httpx.Response(200, json=result if req.url.path == "/search" else e.ev)
    log = []
    with httpx.Client(base_url="http://local", transport=httpx.MockTransport(response)) as client:
        assert gate.audit(client, log, e.state, e.listing, "root", e.row,
                          e.sources[e.path]).startswith("basic_ready")
        assert "file_id" not in log[0]["json"]
        assert log[2]["json"]["file_id"] == "f" and log[2]["json"]["query"].endswith(" page 97")
        bad = deepcopy(e.state)
        bad["page_probe"]["diagnostics"]["files"] = [{"version_id": "v", "applied": True,
                                                     "target_pages": [1]}]
        with pytest.raises(SuiteError, match="routed"):
            gate.audit(client, [], bad, e.listing, "root", e.row, e.sources[e.path])
        bad = deepcopy(e.state)
        bad["page_probe"]["pdf_metadata_lookups"] = {"v": 1}
        with pytest.raises(SuiteError, match="routed"):
            gate.audit(client, [], bad, e.listing, "root", e.row, e.sources[e.path])
        e.state["pdf_metadata"].append({"version_id": "v"})
        with pytest.raises(SuiteError, match="physical page metadata"):
            gate.audit(client, [], e.state, e.listing, "root", e.row, e.sources[e.path])


def test_matching_ids_and_quote_do_not_hide_fabricated_evidence(example):
    e = example
    wrong = e.q["quote"] + " Extra words absent from the document."
    with pytest.raises(SuiteError, match="original source"):
        gate.verify_hit(dict(e.hit, text=wrong), dict(e.ev, text=wrong), "root", e.file, e.version,
                        {"c": dict(e.chunk, text=wrong)}, e.sources[e.path], e.q, "txt")


def test_failed_preflight_never_issues_a_release_verdict(tmp_path, monkeypatch):
    report_dir = tmp_path / "reports"
    monkeypatch.setattr(gate, "REPORTS", report_dir)
    monkeypatch.setattr(gate, "stage", lambda *unused: None)
    def unavailable(*unused):
        raise SuiteError("no candidate stack")
    monkeypatch.setattr(gate.stack, "start", unavailable)
    flags = tmp_path / "flags.env"
    flags.write_text("TEXT_PARSING_ENABLED=true\nDOCX_PARSING_ENABLED=false\n")
    args = ["--candidate-sha", "a" * 40, "--run-id", "local-negative", "--flags", str(flags),
            "--formats", "txt"]
    assert gate.main(args) == 1
    report = json.loads((report_dir / "local-negative/actual.json").read_bytes())
    assert report["status"] == "UNVERIFIED" and not report["http"]
    assert set(report["formats"].values()) == {"UNVERIFIED"}
    assert {p.split("/")[0] for p, c in report["cases"].items() if c["in_scope"]} == {"txt", "pdf"}
    with pytest.raises(SystemExit):
        gate.main(args)  # Previous report must not be overwritten.
