"""Model preparation must verify bytes before creating their local manifest."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import search_tools
from services.search.text import MODEL_FILES, MODEL_ID, MODEL_REVISION, PINNED_MODEL_SHA256

REPO = Path(__file__).resolve().parents[2]


def synthetic_model(tmp_path, monkeypatch):
    checksums = {}
    for filename in MODEL_FILES:
        content = f"model preparation test {filename}".encode()
        (tmp_path / filename).write_bytes(content)
        checksums[filename] = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(search_tools, "PINNED_MODEL_SHA256", checksums)
    return checksums


def test_pinned_expected_hashes_match_the_retained_revision_manifest():
    retained = json.loads(
        (REPO / "submissions/week07/evidence/C/model-manifest.json").read_text("utf-8")
    )
    assert retained["model"] == MODEL_ID and retained["revision"] == MODEL_REVISION
    assert retained["sha256"] == PINNED_MODEL_SHA256
    assert set(PINNED_MODEL_SHA256) == set(MODEL_FILES)


def test_official_preparation_pins_download_then_checks_all_files(tmp_path, monkeypatch):
    checksums = synthetic_model(tmp_path, monkeypatch)
    calls = []

    def download(model, **kwargs):
        calls.append((model, kwargs))

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    search_tools.prepare_model(tmp_path)
    model, options = calls[0]
    assert model == "intfloat/multilingual-e5-small"
    assert options["revision"] == MODEL_REVISION
    assert options["allow_patterns"] == list(MODEL_FILES)
    assert options["local_dir"] == str(tmp_path)
    manifest = json.loads((tmp_path / "model-manifest.json").read_text("utf-8"))
    assert manifest == {"model": MODEL_ID, "revision": MODEL_REVISION, "sha256": checksums}


def test_bad_download_cannot_sign_or_replace_the_manifest(tmp_path, monkeypatch):
    synthetic_model(tmp_path, monkeypatch)
    (tmp_path / "model-manifest.json").write_text("previous manifest", encoding="utf-8")

    def corrupt_download(*args, **kwargs):
        (tmp_path / "model.safetensors").write_bytes(b"wrong revision or incomplete bytes")

    monkeypatch.setitem(
        sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=corrupt_download)
    )
    with pytest.raises(ValueError, match="pinned model checksum mismatch: model.safetensors"):
        search_tools.prepare_model(tmp_path)
    assert (tmp_path / "model-manifest.json").read_text("utf-8") == "previous manifest"


def test_incomplete_preparation_has_no_valid_manifest(tmp_path, monkeypatch):
    synthetic_model(tmp_path, monkeypatch)
    (tmp_path / "tokenizer.json").unlink()
    with pytest.raises(FileNotFoundError):
        search_tools.verified_model_manifest(tmp_path)
    assert not (tmp_path / "model-manifest.json").exists()
