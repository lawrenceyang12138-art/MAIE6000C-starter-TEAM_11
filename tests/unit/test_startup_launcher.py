"""The standard-library launcher installs in Docker without mutating host Python."""

from __future__ import annotations

import json
from urllib.error import URLError

import pytest

from scripts import start


@pytest.fixture
def launcher_repo(tmp_path):
    (tmp_path / ".env.example").write_text(
        "FRONTEND_DATA_MODE=api\nAPI_HOST_PORT=8000\nFRONTEND_HOST_PORT=3000\n",
        encoding="utf-8",
    )
    (tmp_path / "Dockerfile").write_text("FROM python:3.11-slim\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def docker(monkeypatch):
    calls = []

    def run(command, repo, *, capture=False):
        calls.append(command)
        return "image-sha" if capture else ""

    monkeypatch.setattr(start, "run", run)
    for key in (
        "FRONTEND_DATA_MODE", "FRONTEND_API_BASE_URL", "API_HOST_PORT", "FRONTEND_HOST_PORT",
    ):
        monkeypatch.delenv(key, raising=False)
    return calls


def test_first_start_builds_dependencies_then_starts_and_waits(launcher_repo, docker, monkeypatch):
    observed = []

    def wait(url, timeout):
        observed.append((url, timeout))
        assert docker[-1] == ["docker", "compose", "up", "-d", "--no-build"]
        return 0

    monkeypatch.setattr(start, "wait_for_model", wait)
    assert start.main([], repo=launcher_repo) == 0
    assert ["docker", "compose", "--progress", "plain", "build"] in docker
    assert observed == [("http://127.0.0.1:8000", 1800)]
    assert start.read_env(launcher_repo / ".env")["FRONTEND_DATA_MODE"] == "api"
    assert json.loads((launcher_repo / "work/startup-build.json").read_text())["fingerprint"]


def test_restart_reuses_installed_images_but_source_changes_rebuild(launcher_repo, docker):
    assert start.main(["--no-wait"], repo=launcher_repo) == 0
    docker.clear()
    assert start.main(["--no-wait"], repo=launcher_repo) == 0
    assert not any("build" in command for command in docker)
    (launcher_repo / "Dockerfile").write_text("FROM python:3.11-slim\nENV CHANGED=1\n")
    docker.clear()
    assert start.main(["--no-wait"], repo=launcher_repo) == 0
    assert ["docker", "compose", "--progress", "plain", "build"] in docker


@pytest.mark.parametrize("changed_input", [
    "submissions/week07/gold-queries.json",
    "submissions/week07/gold-queries.freeze.json",
    "submissions/week07/evidence/C/model-manifest.json",
])
def test_changed_packaged_evaluation_input_rebuilds_cached_images(
    launcher_repo, docker, changed_input,
):
    source = launcher_repo / changed_input
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_text('{"revision": 1}\n', encoding="utf-8")

    build = ["docker", "compose", "--progress", "plain", "build"]
    assert start.main(["--no-wait"], repo=launcher_repo) == 0
    original = start.build_fingerprint(launcher_repo, {})
    docker.clear()
    assert start.main(["--no-wait"], repo=launcher_repo) == 0
    assert build not in docker

    # A same-length content edit must invalidate the saved image fingerprint.
    source.write_text('{"revision": 2}\n', encoding="utf-8")
    updated = start.build_fingerprint(launcher_repo, {})
    assert updated != original
    docker.clear()
    assert start.main(["--no-wait"], repo=launcher_repo) == 0
    assert build in docker
    assert docker.index(build) < docker.index(["docker", "compose", "up", "-d", "--no-build"])
    marker = launcher_repo / "work/startup-build.json"
    assert json.loads(marker.read_text(encoding="utf-8"))["fingerprint"] == updated

    docker.clear()
    assert start.main(["--no-wait"], repo=launcher_repo) == 0
    assert build not in docker


def test_new_evaluation_reports_do_not_rebuild_images(launcher_repo, docker):
    assert start.main(["--no-wait"], repo=launcher_repo) == 0
    original = start.build_fingerprint(launcher_repo, {})
    evidence = launcher_repo / "submissions/week07/evidence/20261031-w7"
    evidence.mkdir(parents=True)
    (evidence / "README.md").write_text("Updated verification notes\n", encoding="utf-8")
    (evidence / "results.json").write_text('{"passed": true}\n', encoding="utf-8")

    assert start.build_fingerprint(launcher_repo, {}) == original
    docker.clear()
    assert start.main(["--no-wait"], repo=launcher_repo) == 0
    assert ["docker", "compose", "--progress", "plain", "build"] not in docker


def test_rebuild_flag_and_missing_image_force_build(launcher_repo, docker, monkeypatch):
    start.main(["--no-wait"], repo=launcher_repo)
    docker.clear()
    assert start.main(["--no-wait", "--rebuild"], repo=launcher_repo) == 0
    assert ["docker", "compose", "--progress", "plain", "build"] in docker
    monkeypatch.setattr(start, "images_available", lambda repo: False)
    assert start.needs_build(launcher_repo, start.build_fingerprint(launcher_repo, {}))


def test_image_reuse_checks_image_store_not_created_containers(launcher_repo, monkeypatch):
    calls = []

    def run(command, repo, *, capture=False):
        calls.append(command)
        if command == ["docker", "compose", "config", "--images"]:
            return "local-api\nlocal-frontend\nlocal-api"
        assert command == [
            "docker", "image", "inspect", "local-api", "local-frontend", "--format", "{{.Id}}",
        ]
        return "sha256:first\nsha256:second"

    monkeypatch.setattr(start, "run", run)
    assert start.images_available(launcher_repo)
    assert len(calls) == 2


def test_preserves_existing_env_and_explicit_mock(launcher_repo, docker, capsys):
    env = launcher_repo / ".env"
    content = b"FRONTEND_DATA_MODE=mock\nAPI_HOST_PORT=18000\n# keep custom credentials\n"
    env.write_bytes(content)
    assert start.main(["--no-wait"], repo=launcher_repo) == 0
    assert env.read_bytes() == content
    assert "Preserving explicit mock mode" in capsys.readouterr().out


def test_check_changes_no_files_or_services(launcher_repo, docker):
    assert start.main(["--check"], repo=launcher_repo) == 0
    assert not (launcher_repo / ".env").exists()
    assert not (launcher_repo / "work").exists()
    assert len(docker) == 2


def test_failed_build_does_not_start_or_publish_marker(launcher_repo, monkeypatch):
    def run(command, repo, *, capture=False):
        if "build" in command:
            raise start.StartupError("build failed")
        assert "up" not in command
        return "available"

    monkeypatch.setattr(start, "run", run)
    assert start.main(["--no-wait"], repo=launcher_repo) == 1
    assert not (launcher_repo / "work/startup-build.json").exists()


def test_failed_daemon_does_not_create_env(launcher_repo, monkeypatch, capsys):
    def run(command, repo, *, capture=False):
        raise start.StartupError("Docker is not running")

    monkeypatch.setattr(start, "run", run)
    assert start.main([], repo=launcher_repo) == 1
    assert not (launcher_repo / ".env").exists()
    assert "Docker is not running" in capsys.readouterr().err


def test_wait_reports_real_progress_and_requires_true_ready(monkeypatch, capsys):
    statuses = iter([
        {"state": "downloading", "downloaded_bytes": 1048576, "total_bytes": 2097152,
         "stage_progress": 50, "message": "Downloading pinned files."},
        {"state": "ready", "ready": False},
        {"state": "warming_up", "ready": False},
        {"state": "ready", "ready": True},
    ])
    monkeypatch.setattr(start, "fetch_setup", lambda url: next(statuses))
    monkeypatch.setattr(start.time, "sleep", lambda seconds: None)
    assert start.wait_for_model("http://127.0.0.1:8000", 3) == 0
    output = capsys.readouterr().out
    assert "50.0% (1.0 MiB / 2.0 MiB)" in output
    assert "[warming_up]" in output


@pytest.mark.parametrize("state,expected", [("disabled", 0), ("error", 1)])
def test_disabled_and_failed_preparation_are_not_claimed_ready(
    monkeypatch, capsys, state, expected,
):
    monkeypatch.setattr(start, "fetch_setup", lambda url: {"state": state, "ready": False})
    assert start.wait_for_model("http://127.0.0.1:8000", 1) == expected
    assert "Keyword search remains available" in capsys.readouterr().out


def test_api_unavailable_times_out_without_stopping_stack(monkeypatch, capsys):
    ticks = iter([0, 0, 1, 2])
    monkeypatch.setattr(start.time, "monotonic", lambda: next(ticks))
    monkeypatch.setattr(start.time, "sleep", lambda seconds: None)

    def unavailable(url):
        raise URLError("not started")

    monkeypatch.setattr(start, "fetch_setup", unavailable)
    assert start.wait_for_model("http://127.0.0.1:8000", 1) == 1
    assert "not a model-ready result" in capsys.readouterr().out


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8000", "http://example.com", "http://user:secret@127.0.0.1:8000",
    "http://127.0.0.1:8000/path", "http://127.0.0.1:8000?x=1", "http://127.0.0.1:invalid",
    "http://127.0.0.1:0", "http://[invalid",
])
def test_setup_origin_must_be_local_without_credentials(url):
    with pytest.raises(start.StartupError):
        start.local_url(url)


def test_launcher_does_not_hash_or_mutate_external_symlinks(launcher_repo):
    before = start.build_fingerprint(launcher_repo, {})
    excluded = launcher_repo / "frontend/node_modules"
    excluded.mkdir(parents=True)
    (excluded / "module.js").write_text("ignored dependency cache")
    assert start.build_fingerprint(launcher_repo, {}) == before
    cache = launcher_repo / "models"
    cache.mkdir()
    (cache / "model.safetensors").write_bytes(b"download progress")
    assert start.build_fingerprint(launcher_repo, {}) == before


def test_env_parser_supports_quotes_export_comments_and_never_executes(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        '# comment\nexport API_HOST_PORT="18000"\nFRONTEND_DATA_MODE=api # comment\n'
        "TEXT='$(do not execute)'\n", encoding="utf-8",
    )
    assert start.read_env(path) == {
        "API_HOST_PORT": "18000", "FRONTEND_DATA_MODE": "api", "TEXT": "$(do not execute)",
    }


def test_changed_frontend_build_mode_invalidates_image(launcher_repo, monkeypatch):
    monkeypatch.delenv("FRONTEND_DATA_MODE", raising=False)
    first = start.build_fingerprint(launcher_repo, {"FRONTEND_DATA_MODE": "api"})
    second = start.build_fingerprint(launcher_repo, {"FRONTEND_DATA_MODE": "mock"})
    assert first != second


def test_marker_publication_is_atomic_and_failed_replace_preserves_old_marker(
    launcher_repo, monkeypatch,
):
    start.write_build_marker(launcher_repo, "old")
    marker = launcher_repo / "work/startup-build.json"

    def fail_replace(source, target):
        assert json.loads(source.read_text())["fingerprint"] == "new"
        assert json.loads(target.read_text())["fingerprint"] == "old"
        raise OSError("test interrupted replacement")

    monkeypatch.setattr(start.os, "replace", fail_replace)
    with pytest.raises(OSError):
        start.write_build_marker(launcher_repo, "new")
    assert json.loads(marker.read_text())["fingerprint"] == "old"
    assert list(marker.parent.iterdir()) == [marker]


@pytest.mark.parametrize("value", ["0", "-1", "nan", "inf"])
def test_invalid_wait_duration_is_rejected_before_docker(launcher_repo, docker, value):
    with pytest.raises(SystemExit):
        start.main([f"--timeout={value}"], repo=launcher_repo)
    assert not docker
