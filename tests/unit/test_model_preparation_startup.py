"""Independent startup preparation checks use tiny, SHA-pinned synthetic bytes."""

from __future__ import annotations

import hashlib
import json
from threading import Event, Thread

import httpx
import pytest

from services.search import model_preparation as preparation


@pytest.fixture
def model_files(monkeypatch):
    monkeypatch.delenv("HF_HUB_OFFLINE", raising=False)
    monkeypatch.delenv("TRANSFORMERS_OFFLINE", raising=False)
    files = {
        "config.json": b'{"local":true}',
        "model.safetensors": b"0123456789abcdefghijklmnopqrstuv",
        "1_Dense/config.json": b'{"dimensions":128}',
    }
    monkeypatch.setattr(preparation, "MODEL_FILES", tuple(files))
    monkeypatch.setattr(preparation, "MODEL_FILE_BYTES", {
        name: len(content) for name, content in files.items()
    })
    monkeypatch.setattr(preparation, "PINNED_MODEL_SHA256", {
        name: hashlib.sha256(content).hexdigest() for name, content in files.items()
    })
    monkeypatch.setattr(preparation, "BLOCK_BYTES", 4)
    return files


def transport(monkeypatch, handler):
    client = httpx.Client
    monkeypatch.setattr(
        preparation.httpx,
        "Client",
        lambda **kwargs: client(transport=httpx.MockTransport(handler), **kwargs),
    )


def run_prepare(path, events, *, cancel=None, **kwargs):
    preparation.prepare_local_model(
        path,
        progress=lambda **event: events.append(event),
        cancel=cancel or Event(),
        retries=1,
        **kwargs,
    )


def seed(path, files):
    for name, content in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)


def test_missing_model_downloads_official_pinned_urls_and_reports_real_progress(
    tmp_path, monkeypatch, model_files,
):
    calls = []

    def handler(request):
        prefix = f"/{preparation.MODEL_NAME}/resolve/{preparation.MODEL_REVISION}/"
        assert request.url.host == "huggingface.co"
        assert request.url.path.startswith(prefix)
        name = request.url.path.removeprefix(prefix)
        assert request.headers["accept-encoding"] == "identity"
        calls.append(name)
        return httpx.Response(200, content=model_files[name])

    transport(monkeypatch, handler)
    events = []
    run_prepare(tmp_path / "new-model", events)
    assert calls == list(model_files)
    assert {event["state"] for event in events if "state" in event} == {
        "checking_model", "downloading", "verifying",
    }
    total = sum(map(len, model_files.values()))
    assert max(event.get("downloaded_bytes", 0) for event in events) == total
    assert max(event.get("stage_progress", 0) for event in events) == 100
    manifest = json.loads((tmp_path / "new-model/model-manifest.json").read_text("utf-8"))
    assert manifest == {
        "model": preparation.MODEL_ID,
        "revision": preparation.MODEL_REVISION,
        "sha256": preparation.PINNED_MODEL_SHA256,
    }
    assert not list((tmp_path / "new-model").rglob("*.part"))


def test_verified_model_is_reused_fully_offline_and_manifest_is_rebuilt(
    tmp_path, monkeypatch, model_files,
):
    seed(tmp_path, model_files)

    def no_network(**kwargs):
        pytest.fail("verified files must not even create an HTTP client")

    monkeypatch.setattr(preparation.httpx, "Client", no_network)
    events = []
    run_prepare(tmp_path, events, allow_download=False)
    assert (tmp_path / "model-manifest.json").is_file()
    assert not any(event.get("state") == "downloading" for event in events)
    assert {name: (tmp_path / name).read_bytes() for name in model_files} == model_files


def test_only_corrupt_existing_file_is_repaired(tmp_path, monkeypatch, model_files):
    seed(tmp_path, model_files)
    corrupt = "model.safetensors"
    (tmp_path / corrupt).write_bytes(b"x" * len(model_files[corrupt]))
    calls = []

    def handler(request):
        calls.append(request.url.path)
        return httpx.Response(200, content=model_files[corrupt])

    transport(monkeypatch, handler)
    run_prepare(tmp_path, [])
    assert len(calls) == 1
    assert calls[0].endswith("/" + corrupt)
    assert (tmp_path / corrupt).read_bytes() == model_files[corrupt]


def test_partial_download_resumes_only_at_validated_range(tmp_path, monkeypatch, model_files):
    seed(tmp_path, model_files)
    name = "model.safetensors"
    (tmp_path / name).unlink()
    partial = tmp_path / (name + ".part")
    partial.write_bytes(model_files[name][:9])
    calls = []

    def handler(request):
        calls.append(request.headers.get("range"))
        data = model_files[name]
        return httpx.Response(
            206,
            headers={"Content-Range": f"bytes 9-{len(data) - 1}/{len(data)}"},
            content=data[9:],
        )

    transport(monkeypatch, handler)
    run_prepare(tmp_path, [])
    assert calls == ["bytes=9-"]
    assert not partial.exists()
    assert (tmp_path / name).read_bytes() == model_files[name]


def test_server_ignoring_range_restarts_instead_of_appending(tmp_path, monkeypatch, model_files):
    seed(tmp_path, model_files)
    name = "model.safetensors"
    (tmp_path / name).unlink()
    (tmp_path / (name + ".part")).write_bytes(b"wrong partial")

    def handler(request):
        assert request.headers["range"] == "bytes=13-"
        return httpx.Response(200, content=model_files[name])

    transport(monkeypatch, handler)
    run_prepare(tmp_path, [])
    assert (tmp_path / name).read_bytes() == model_files[name]


@pytest.mark.parametrize(
    ("status", "headers", "body", "reason"),
    [
        (206, {"Content-Range": "bytes 1-13/14"}, b"x" * 13,
         "model_download_invalid_range"),
        (206, {}, b"x" * 13, "model_download_invalid_range"),
        (200, {}, b"short", "model_download_size_mismatch"),
        (200, {}, b"x" * 15, "model_download_size_mismatch"),
        (200, {}, b"x" * 14, "model_checksum_mismatch"),
        (404, {}, b"not found", "model_download_failed"),
    ],
)
def test_bad_download_does_not_publish_file_or_overwrite_existing_manifest(
    tmp_path, monkeypatch, model_files, status, headers, body, reason,
):
    seed(tmp_path, model_files)
    target = tmp_path / "config.json"
    target.unlink()
    previous = tmp_path / "model-manifest.json"
    previous.write_text("previous verified manifest", encoding="utf-8")
    transport(monkeypatch, lambda request: httpx.Response(status, headers=headers, content=body))
    with pytest.raises(preparation.PreparationError, match="^" + reason + "$"):
        run_prepare(tmp_path, [])
    assert not target.exists()
    assert previous.read_text("utf-8") == "previous verified manifest"
    assert not list(tmp_path.glob(".manifest-*"))


def test_interrupted_download_retains_partial_for_next_start(
    tmp_path, monkeypatch, model_files,
):
    seed(tmp_path, model_files)
    name = "model.safetensors"
    (tmp_path / name).unlink()

    class Interrupted(httpx.SyncByteStream):
        def __iter__(self):
            yield model_files[name][:12]
            raise httpx.ReadError("network interruption with secret URL must not escape")

    transport(monkeypatch, lambda request: httpx.Response(200, stream=Interrupted()))
    with pytest.raises(preparation.PreparationError, match="^model_download_failed$"):
        run_prepare(tmp_path, [])
    assert not (tmp_path / "model-manifest.json").exists()
    partial = tmp_path / (name + ".part")
    assert partial.read_bytes() == model_files[name][:12]


def test_complete_verified_partial_needs_no_network_request(
    tmp_path, monkeypatch, model_files,
):
    seed(tmp_path, model_files)
    name = "model.safetensors"
    (tmp_path / name).unlink()
    (tmp_path / (name + ".part")).write_bytes(model_files[name])
    transport(monkeypatch, lambda request: pytest.fail("complete partial already has pinned bytes"))
    run_prepare(tmp_path, [])
    assert (tmp_path / name).read_bytes() == model_files[name]


def test_disabled_download_does_not_contact_network_or_create_manifest(
    tmp_path, monkeypatch, model_files,
):
    monkeypatch.setattr(preparation.httpx, "Client", lambda **kwargs: pytest.fail("no network"))
    with pytest.raises(preparation.PreparationError, match="^local_model_missing_or_corrupt$"):
        run_prepare(tmp_path, [], allow_download=False)
    assert not (tmp_path / "model-manifest.json").exists()


@pytest.mark.parametrize("name", ["HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"])
def test_standard_offline_flags_override_auto_download(
    tmp_path, monkeypatch, model_files, name,
):
    monkeypatch.setenv(name, "1")
    monkeypatch.setattr(preparation.httpx, "Client", lambda **kwargs: pytest.fail("offline"))
    with pytest.raises(preparation.PreparationError, match="^local_model_missing_or_corrupt$"):
        run_prepare(tmp_path, [], allow_download=True)
    assert not (tmp_path / "model-manifest.json").exists()


def test_cancelled_preparation_never_reports_ready_or_creates_manifest(tmp_path, model_files):
    cancel = Event()
    cancel.set()
    events = []
    with pytest.raises(preparation.PreparationCancelled):
        run_prepare(tmp_path, events, cancel=cancel)
    assert not (tmp_path / "model-manifest.json").exists()
    assert not any(event.get("state") == "ready" for event in events)


def test_cancellation_during_download_keeps_unverified_bytes_private(
    tmp_path, monkeypatch, model_files,
):
    cancel = Event()

    class CancelledStream(httpx.SyncByteStream):
        def __iter__(self):
            yield model_files["config.json"][:4]
            cancel.set()
            yield model_files["config.json"][4:]

    transport(monkeypatch, lambda request: httpx.Response(200, stream=CancelledStream()))
    with pytest.raises(preparation.PreparationCancelled):
        run_prepare(tmp_path, [], cancel=cancel)
    assert not (tmp_path / "config.json").exists()
    assert not (tmp_path / "model-manifest.json").exists()


def test_model_filename_cannot_escape_storage(tmp_path, monkeypatch):
    filename = "../outside-model"
    monkeypatch.setattr(preparation, "MODEL_FILES", (filename,))
    monkeypatch.setattr(preparation, "MODEL_FILE_BYTES", {filename: 1})
    monkeypatch.setattr(preparation, "PINNED_MODEL_SHA256", {filename: "0" * 64})
    with pytest.raises(preparation.PreparationError, match="^model_path_outside_storage$"):
        run_prepare(tmp_path / "storage", [])
    assert not (tmp_path / "outside-model").exists()


def test_lock_contention_is_cancellable_and_a_leftover_lock_file_is_not_a_lock(
    tmp_path, model_files,
):
    cancel = Event()
    blocked = Event()
    failures = []

    def contender():
        try:
            preparation.prepare_local_model(
                tmp_path,
                progress=lambda **event: blocked.set()
                if "Waiting" in event.get("message", "") else None,
                cancel=cancel,
                allow_download=False,
            )
        except preparation.PreparationError as error:
            failures.append(str(error))

    with preparation._preparation_lock(tmp_path, Event(), lambda **event: None):
        thread = Thread(target=contender)
        thread.start()
        assert blocked.wait(3), "second process/thread must wait for the actual OS lock"
        cancel.set()
        thread.join(3)
        assert not thread.is_alive()
    assert failures == ["preparation_cancelled"]
    seed(tmp_path, model_files)
    run_prepare(tmp_path, [], allow_download=False)
    assert (tmp_path / "model-manifest.json").is_file()
