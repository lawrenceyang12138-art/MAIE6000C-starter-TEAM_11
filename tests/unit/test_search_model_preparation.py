"""Model preparation must verify bytes before creating their local manifest."""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import search_tools
from services.search.text import (
    MODEL_FILES,
    MODEL_ID,
    MODEL_NAME,
    MODEL_REVISION,
    PINNED_MODEL_SHA256,
)

REPO = Path(__file__).resolve().parents[2]


def synthetic_model(tmp_path, monkeypatch):
    checksums = {}
    for filename in MODEL_FILES:
        content = f"model preparation test {filename}".encode()
        target = tmp_path / filename
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        checksums[filename] = hashlib.sha256(content).hexdigest()
    monkeypatch.setattr(search_tools, "PINNED_MODEL_SHA256", checksums)
    return checksums


def test_pinned_expected_hashes_cover_the_active_model_files():
    assert MODEL_NAME == "perplexity-ai/pplx-embed-v2-late-0.6b"
    assert MODEL_REVISION == "7bba8e7cf2075dec747fa8557f41eb90e70361ed"
    assert MODEL_ID == f"{MODEL_NAME}@{MODEL_REVISION}"
    assert set(PINNED_MODEL_SHA256) == set(MODEL_FILES)
    assert all(len(value) == 64 and set(value) <= set("0123456789abcdef")
               for value in PINNED_MODEL_SHA256.values())


def test_retired_e5_manifest_remains_historical_evidence():
    retained = json.loads(
        (REPO / "submissions/week07/evidence/C/model-manifest.json").read_text("utf-8")
    )
    assert retained["model"] == (
        "intfloat/multilingual-e5-small@614241f622f53c4eeff9890bdc4f31cfecc418b3"
    )
    assert retained["revision"] == "614241f622f53c4eeff9890bdc4f31cfecc418b3"
    assert retained["model"] != MODEL_ID
    assert retained["sha256"]["model.safetensors"] == (
        "1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477"
    )


def test_official_preparation_pins_download_then_checks_all_files(tmp_path, monkeypatch):
    checksums = synthetic_model(tmp_path, monkeypatch)
    calls = []

    def download(model, **kwargs):
        calls.append((model, kwargs))

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    search_tools.prepare_model(tmp_path)
    model, options = calls[0]
    assert model == MODEL_NAME
    assert options["revision"] == MODEL_REVISION
    assert options["allow_patterns"] == list(MODEL_FILES)
    assert options["local_dir"] == str(tmp_path)
    manifest = json.loads((tmp_path / "model-manifest.json").read_text("utf-8"))
    assert manifest == {"model": MODEL_ID, "revision": MODEL_REVISION, "sha256": checksums}


def test_preparation_supports_nested_model_modules_and_new_destination(tmp_path, monkeypatch):
    destination = tmp_path / "new" / "model"
    checksums = {
        filename: hashlib.sha256(f"download {filename}".encode()).hexdigest()
        for filename in MODEL_FILES
    }
    monkeypatch.setattr(search_tools, "PINNED_MODEL_SHA256", checksums)

    def download(model, **kwargs):
        assert model == MODEL_NAME
        assert destination.is_dir()
        for filename in kwargs["allow_patterns"]:
            target = destination / filename
            assert target.parent.is_dir()
            target.write_bytes(f"download {filename}".encode())

    monkeypatch.setitem(sys.modules, "huggingface_hub", SimpleNamespace(snapshot_download=download))
    search_tools.prepare_model(destination)
    manifest = json.loads((destination / "model-manifest.json").read_text("utf-8"))
    assert manifest["sha256"] == checksums
    assert (destination / "1_Dense/model.safetensors").is_file()


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
