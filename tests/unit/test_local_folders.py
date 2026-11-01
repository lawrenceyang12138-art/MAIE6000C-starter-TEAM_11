"""Native consent, durable directory mounts and the loopback bridge boundary."""

from __future__ import annotations

import ctypes
import http.client
import json
import os
import subprocess
import threading
import time
import uuid
from types import SimpleNamespace

import pytest

from scripts import local_folders as folders


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.delenv("SOURCE_MOUNTS", raising=False)
    monkeypatch.delenv("LOCAL_FOLDER_BRIDGE_PORT", raising=False)
    monkeypatch.delenv("FRONTEND_HOST_PORT", raising=False)
    (tmp_path / "compose.yaml").write_text("services: {}\n", encoding="utf-8")
    folders.prepare_sources(tmp_path, {})
    return tmp_path


def registry(repo, mounts):
    folders._write_json(folders.state_dir(repo) / "registry.json", {"mounts": mounts})


def selection(bridge, path):
    operation_id = str(uuid.uuid4())
    bridge.operations[operation_id] = {
        "operation_id": operation_id, "state": "selected", "_path": str(path),
        "folder_name": path.name, "display_path": str(path),
    }
    bridge._save(bridge.operations[operation_id])
    return operation_id


def test_overlay_preserves_configured_sources_and_binds_only_existing_authorized_folders(repo):
    source = repo / "中文 $source folder"
    source.mkdir()
    missing = repo / "removed"
    registry(repo, {
        "local-a": {"path": str(source)}, "local-b": {"path": str(missing)},
    })
    folders.prepare_sources(repo, {"SOURCE_MOUNTS": '{"corpus":"/source/corpus","team":"/team"}'})
    overlay = folders._read_json(folders.state_dir(repo) / "compose.sources.json", None)
    assert overlay["services"]["api"] == overlay["services"]["worker"]
    service = overlay["services"]["api"]
    assert json.loads(service["environment"]["SOURCE_MOUNTS"]) == {
        "corpus": "/source/corpus", "team": "/team",
        "local-a": "/source/local/local-a", "local-b": "/source/local/local-b",
    }
    assert service["volumes"] == [{
        "type": "bind", "source": str(source).replace("$", "$$"),
        "target": "/source/local/local-a", "read_only": True,
        "bind": {"create_host_path": False},
    }]
    command = folders.compose_command(repo, "up", "-d", "--no-build", "api")
    assert command[:4] == ["docker", "compose", "--project-directory", str(repo)]
    assert str(repo / "compose.yaml") in command
    assert str(folders.state_dir(repo) / "compose.sources.json") in command


def test_docker_commands_do_not_open_a_console_window_on_windows(repo, monkeypatch):
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="ok")

    monkeypatch.setattr(folders.subprocess, "run", run)
    monkeypatch.setattr(folders.os, "name", "nt")

    assert folders._run(["docker", "version"], repo) == "ok"
    assert calls[0][1]["creationflags"] == subprocess.CREATE_NO_WINDOW


def test_native_picker_reuses_the_interactive_python_session(repo, monkeypatch):
    scripts = repo / "Scripts"
    scripts.mkdir()
    python = scripts / "python.exe"
    python.touch()
    (scripts / "pythonw.exe").touch()
    monkeypatch.setattr(folders.sys, "executable", str(python))
    monkeypatch.setattr(folders.os, "name", "nt")
    calls = []

    def run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="null", stderr="")

    monkeypatch.setattr(folders.subprocess, "run", run)

    assert folders._native_selection(repo) is None
    assert calls[0][0][0] == str(python)
    assert "creationflags" not in calls[0][1]
    assert calls[0][1]["timeout"] == folders.PICKER_TIMEOUT_SECONDS


def test_windowed_launcher_interpreter_is_promoted_to_console_peer(repo, monkeypatch):
    scripts = repo / "Scripts"
    scripts.mkdir()
    python = scripts / "python.exe"
    python.touch()
    monkeypatch.setattr(folders.sys, "executable", str(scripts / "pythonw.exe"))
    assert folders._interactive_python() == python


def test_picker_owner_falls_back_to_visible_console_when_foreground_is_hidden():
    class User32:
        def GetForegroundWindow(self):
            return 0x1234

        def IsWindow(self, handle):
            return handle in {0x1234, 0x5678}

        def IsWindowVisible(self, handle):
            return handle == 0x5678

    class Kernel32:
        def GetConsoleWindow(self):
            return 0x5678

    assert folders._picker_owner(User32(), Kernel32()) == 0x5678


def test_picker_owner_keeps_a_visible_foreground_window():
    class User32:
        def GetForegroundWindow(self):
            return 0x1234

        def IsWindow(self, handle):
            return handle in {0x1234, 0x5678}

        def IsWindowVisible(self, handle):
            return True

    class Kernel32:
        def GetConsoleWindow(self):
            raise AssertionError("A visible foreground window must remain the owner")

    assert folders._picker_owner(User32(), Kernel32()) == 0x1234


def test_windows_folder_dialog_uses_the_shell_picker(monkeypatch):
    monkeypatch.setattr(folders.os, "name", "nt")
    monkeypatch.setattr(folders, "_windows_shell_choose_folder", lambda: r"C:\中文 folder")
    assert folders.choose_folder() == r"C:\中文 folder"


@pytest.mark.skipif(os.name != "nt", reason="Windows Shell COM interfaces are only available on Windows")
def test_windows_shell_picker_uses_visible_owner_and_returns_unicode_path(monkeypatch):
    from ctypes import wintypes

    callbacks = []
    events = []

    class Interface(ctypes.Structure):
        _fields_ = [("vtable", ctypes.POINTER(ctypes.c_void_p))]

    def make_interface(size, methods):
        vtable = (ctypes.c_void_p * size)()
        for index, (result_type, argument_types, callback) in methods.items():
            function = ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)(callback)
            callbacks.append(function)
            vtable[index] = ctypes.cast(function, ctypes.c_void_p).value
        instance = Interface(ctypes.cast(vtable, ctypes.POINTER(ctypes.c_void_p)))
        return instance, ctypes.cast(ctypes.pointer(instance), ctypes.c_void_p)

    path_buffer = ctypes.create_unicode_buffer(r"C:\用户 files\中文 folder")

    def get_options(this, output):
        output.contents.value = 0
        return 0

    def set_options(this, value):
        events.append(("options", value))
        return 0

    def set_title(this, value):
        events.append(("title", value))
        return 0

    def show(this, owner):
        events.append(("owner", owner))
        return 0

    def get_result(this, output):
        output.contents.value = shell_item_address.value
        return 0

    dialog, dialog_address = make_interface(21, {
        2: (None, [], lambda this: None),
        3: (ctypes.c_long, [wintypes.HWND], show),
        9: (ctypes.c_long, [wintypes.DWORD], set_options),
        10: (ctypes.c_long, [ctypes.POINTER(wintypes.DWORD)], get_options),
        17: (ctypes.c_long, [wintypes.LPCWSTR], set_title),
        20: (ctypes.c_long, [ctypes.POINTER(ctypes.c_void_p)], get_result),
    })

    def get_display_name(this, kind, output):
        assert kind == 0x80058000
        output[0] = ctypes.cast(path_buffer, ctypes.c_wchar_p)
        return 0

    shell_item, shell_item_address = make_interface(6, {
        2: (None, [], lambda this: None),
        5: (ctypes.c_long, [wintypes.DWORD, ctypes.POINTER(ctypes.c_wchar_p)], get_display_name),
    })

    class NativeFunction:
        def __init__(self, function):
            self.function = function

        def __call__(self, *args):
            return self.function(*args)

    class Ole32:
        CoInitializeEx = NativeFunction(lambda *args: 0)
        CoCreateInstance = NativeFunction(lambda *args: setattr(args[-1]._obj, "value", dialog_address.value) or 0)
        CoTaskMemFree = NativeFunction(lambda value: events.append(("free", value.value)))
        CoUninitialize = NativeFunction(lambda: events.append(("uninitialize",)))

    class User32:
        GetForegroundWindow = NativeFunction(lambda: 0x1234)
        IsWindow = NativeFunction(lambda handle: True)
        IsWindowVisible = NativeFunction(lambda handle: True)

    class Kernel32:
        GetConsoleWindow = NativeFunction(lambda: 0x5678)

    monkeypatch.setattr(ctypes, "OleDLL", lambda name: Ole32())
    libraries = {"user32": User32(), "kernel32": Kernel32()}
    monkeypatch.setattr(ctypes, "WinDLL", lambda name, **kwargs: libraries[name])

    assert folders._windows_shell_choose_folder() == r"C:\用户 files\中文 folder"
    assert ("owner", 0x1234) in events
    assert events[0] == ("options", 0x20 | 0x40 | 0x800 | 0x8)
    assert ("title", "Choose a folder for FileTrace (read-only)") in events


@pytest.mark.skipif(os.name != "nt", reason="Windows native libraries are only available on Windows")
def test_windows_shell_picker_loads_real_libraries_before_com_initialization(monkeypatch):
    class StopBeforeDialog(Exception):
        pass

    class StopAtCOM:
        argtypes = None
        restype = None

        def __call__(self, *args):
            raise StopBeforeDialog

    ole32 = ctypes.OleDLL("ole32")
    ole32.CoInitializeEx = StopAtCOM()
    monkeypatch.setattr(ctypes, "OleDLL", lambda name: ole32)

    # Load actual user32/kernel32 entry points, without opening a dialog.
    # A mock DLL must not conceal a function bound to the wrong library.
    with pytest.raises(StopBeforeDialog):
        folders._windows_shell_choose_folder()


def test_picker_timeout_fails_the_saved_selection(repo, monkeypatch):
    scripts = repo / "Scripts"
    scripts.mkdir()
    python = scripts / "python.exe"
    python.touch()
    monkeypatch.setattr(folders.sys, "executable", str(python))
    monkeypatch.setattr(folders.os, "name", "nt")
    calls = []

    def run(command, **kwargs):
        calls.append(kwargs)
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(folders.subprocess, "run", run)
    with pytest.raises(folders.FolderError, match="native_picker_timeout"):
        folders._native_selection(repo)
    assert calls[0]["timeout"] == folders.PICKER_TIMEOUT_SECONDS

    bridge = folders.Bridge(repo, {})
    operation_id = str(uuid.uuid4())
    bridge.operations[operation_id] = {"operation_id": operation_id, "state": "selecting"}
    monkeypatch.setattr(
        folders, "_native_selection",
        lambda repo: (_ for _ in ()).throw(folders.FolderError("native_picker_timeout")),
    )
    bridge._select(operation_id)
    assert bridge.get(operation_id) == {
        "operation_id": operation_id, "state": "failed", "error_code": "native_picker_timeout",
    }


def test_invalid_config_fails_without_overwriting_existing_overlay(repo):
    overlay = folders.state_dir(repo) / "compose.sources.json"
    original = overlay.read_bytes()
    with pytest.raises(folders.FolderError, match="source_mounts_invalid"):
        folders.prepare_sources(repo, {"SOURCE_MOUNTS": '["bad"]'})
    assert overlay.read_bytes() == original


def test_configuration_matches_launcher_export_quotes_and_comments(repo):
    (repo / ".env").write_text(
        '# local choices\nexport FRONTEND_HOST_PORT = "3005"\n'
        'SOURCE_MOUNTS={"corpus":"/source/corpus"} # operator note\n'
        "PLAIN=value # note\nSINGLE='unchanged # literal'\n",
        encoding="utf-8",
    )
    assert folders._configuration(repo) == {
        "FRONTEND_HOST_PORT": "3005", "SOURCE_MOUNTS": '{"corpus":"/source/corpus"}',
        "PLAIN": "value", "SINGLE": "unchanged # literal",
    }


def test_cancelled_native_selection_does_not_register_a_mount_or_start_docker(repo, monkeypatch):
    bridge = folders.Bridge(repo, {})
    operation_id = str(uuid.uuid4())
    bridge.operations[operation_id] = {"operation_id": operation_id, "state": "selecting"}
    monkeypatch.setattr(folders, "_native_selection", lambda repo: None)
    monkeypatch.setattr(folders, "_run", lambda *args, **kwargs: pytest.fail("Docker was called"))
    bridge._select(operation_id)
    assert bridge.get(operation_id) == {"operation_id": operation_id, "state": "cancelled"}
    assert not (folders.state_dir(repo) / "registry.json").exists()
    assert bridge.select(operation_id)["state"] == "cancelled"


def test_selection_is_durable_and_idempotent_while_picker_is_open(repo, monkeypatch):
    source = repo / "documents"
    source.mkdir()
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def choose(repo):
        calls.append(repo)
        entered.set()
        assert release.wait(2)
        return str(source)

    monkeypatch.setattr(folders, "_native_selection", choose)
    bridge = folders.Bridge(repo, {})
    operation_id = str(uuid.uuid4())
    assert bridge.select(operation_id)["state"] == "selecting"
    assert entered.wait(2)
    assert bridge.select(operation_id)["state"] == "selecting"
    release.set()
    deadline = time.monotonic() + 2
    while bridge.get(operation_id)["state"] == "selecting" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert len(calls) == 1
    restored = folders.Bridge(repo, {}).get(operation_id)
    assert restored["state"] == "selected"
    assert restored["display_path"] == str(source.resolve())
    assert "_path" not in restored
    assert not (folders.state_dir(repo) / "registry.json").exists()


def mock_preparation(monkeypatch, bridge):
    events = []

    def drain(repo, *, allow_missing=False, on_signal=None):
        events.append("drain")
        if on_signal:
            on_signal()

    monkeypatch.setattr(folders, "_drain_worker", drain)
    monkeypatch.setattr(bridge, "_check_quiescent", lambda: events.append("quiescent"))
    monkeypatch.setattr(bridge, "_up", lambda: events.append("up"))
    monkeypatch.setattr(bridge, "_check_mount", lambda mount: events.append("verified"))
    monkeypatch.setattr(folders, "_run", lambda *args, **kwargs: events.append("validate") or "")
    return events


def test_prepare_commits_after_worker_drain_reconnect_and_verification(repo, monkeypatch):
    source = repo / "documents"
    source.mkdir()
    bridge = folders.Bridge(repo, {})
    operation_id = selection(bridge, source)
    events = mock_preparation(monkeypatch, bridge)
    bridge._prepare(operation_id)
    assert events == ["drain", "quiescent", "validate", "up", "verified"]
    result = bridge.get(operation_id)
    assert result["state"] == "ready"
    mount_id = result["mount_id"]
    assert folders._registry(repo)["mounts"][mount_id]["path"] == str(source.resolve())
    assert bridge.prepare(operation_id) == result


def test_selecting_the_same_folder_reuses_its_mount_without_restarting(repo, monkeypatch):
    source = repo / "documents"
    source.mkdir()
    registry(repo, {"local-existing": {"path": str(source.resolve())}})
    bridge = folders.Bridge(repo, {})
    operation_id = selection(bridge, source)
    events = mock_preparation(monkeypatch, bridge)
    bridge._prepare(operation_id)
    assert events == ["verified"]
    assert bridge.get(operation_id)["mount_id"] == "local-existing"


def test_returning_removable_folder_is_remounted_under_its_existing_id(repo, monkeypatch):
    source = repo / "documents"
    source.mkdir()
    registry(repo, {"local-existing": {"path": str(source.resolve())}})
    bridge = folders.Bridge(repo, {})
    operation_id = selection(bridge, source)
    events = mock_preparation(monkeypatch, bridge)
    checks = []

    def check(mount_id):
        checks.append(mount_id)
        if len(checks) == 1:
            raise folders.FolderError("source_mount_unavailable")

    monkeypatch.setattr(bridge, "_check_mount", check)
    bridge._prepare(operation_id)
    assert checks == ["local-existing", "local-existing"]
    assert "drain" in events
    assert bridge.get(operation_id)["mount_id"] == "local-existing"
    assert bridge.get(operation_id)["state"] == "ready"


def test_prepare_uses_updated_source_configuration_over_old_snapshot(repo, monkeypatch):
    source = repo / "documents"
    source.mkdir()
    bridge = folders.Bridge(repo, {"SOURCE_MOUNTS": '{"old":"/old"}'})
    (repo / ".env").write_text(
        'export SOURCE_MOUNTS={"corpus":"/source/corpus","team":"/team"} # comment\n',
        encoding="utf-8",
    )
    operation_id = selection(bridge, source)
    mock_preparation(monkeypatch, bridge)
    bridge._prepare(operation_id)
    overlay = folders._read_json(folders.state_dir(repo) / "compose.sources.json", None)
    mounts = json.loads(overlay["services"]["api"]["environment"]["SOURCE_MOUNTS"])
    assert mounts["team"] == "/team" and "old" not in mounts


def test_failed_reconnection_restores_old_registry_and_overlay(repo, monkeypatch):
    source = repo / "documents"
    source.mkdir()
    bridge = folders.Bridge(repo, {})
    operation_id = selection(bridge, source)
    events = mock_preparation(monkeypatch, bridge)
    attempts = []

    def up():
        attempts.append(True)
        if len(attempts) == 1:
            raise folders.FolderError("api_reconnect_failed")

    monkeypatch.setattr(bridge, "_up", up)
    bridge._prepare(operation_id)
    assert len(attempts) == 2
    assert events.count("drain") == 2
    assert bridge.get(operation_id)["state"] == "failed"
    assert bridge.get(operation_id)["error_code"] == "api_reconnect_failed"
    assert folders._registry(repo) == {"mounts": {}}
    overlay = folders._read_json(folders.state_dir(repo) / "compose.sources.json", None)
    assert overlay["services"]["api"]["volumes"] == []


def test_restart_drains_then_restores_overlay_and_preserves_selection(repo, monkeypatch):
    source = repo / "documents"
    source.mkdir()
    bridge = folders.Bridge(repo, {})
    operation_id = selection(bridge, source)
    bridge._update(operation_id, state="reconnecting", _drain_requested=True)
    overlay = folders.state_dir(repo) / "compose.sources.json"
    folders._write_json(overlay, {"uncommitted": True})
    events = []
    monkeypatch.setattr(folders, "_drain_worker", lambda *args, **kwargs: events.append("drain"))
    folders.prepare_sources(repo, {})
    assert events == ["drain"]
    restored = folders.Bridge(repo, {})
    assert restored.get(operation_id)["state"] == "failed"
    assert restored.get(operation_id)["error_code"] == "preparation_interrupted"
    assert restored.operations[operation_id]["_path"] == str(source)
    assert "uncommitted" not in folders._read_json(overlay, None)


def test_repeated_start_does_not_mark_a_live_choosers_operation_interrupted(repo, monkeypatch):
    bridge = folders.Bridge(repo, {})
    operation_id = str(uuid.uuid4())
    bridge.operations[operation_id] = {"operation_id": operation_id, "state": "selecting"}
    bridge._save(bridge.operations[operation_id])
    with folders._instance_lock(repo):
        folders.prepare_sources(repo, {})
    assert folders.Bridge(repo, {}).get(operation_id)["state"] == "selecting"


def test_drain_retries_an_uncertain_signal_and_never_sends_a_stronger_one(repo, monkeypatch):
    calls = []
    states = iter([{"Running": True}, {"Running": True}, {"Running": False, "ExitCode": 0}])
    monkeypatch.setattr(folders, "_containers", lambda *args: ["worker-id"])
    monkeypatch.setattr(folders, "_require_drain_support", lambda *args: None)
    monkeypatch.setattr(folders, "_container_state", lambda *args: next(states))
    monkeypatch.setattr(folders.time, "sleep", lambda seconds: None)

    def run(command, *args, **kwargs):
        calls.append(command)
        if len(calls) == 1:
            raise folders.FolderError("worker_drain_failed")
        return ""

    monkeypatch.setattr(folders, "_run", run)
    folders._drain_worker(repo)
    assert calls == [["docker", "kill", "--signal=USR1", "worker-id"]] * 2


def test_abnormal_worker_exit_is_rejected(repo, monkeypatch):
    monkeypatch.setattr(folders, "_containers", lambda *args: ["worker-id"])
    monkeypatch.setattr(
        folders, "_container_state", lambda *args: {"Running": False, "ExitCode": 137},
    )
    with pytest.raises(folders.FolderError, match="worker_abnormal_exit"):
        folders._drain_worker(repo)


def test_normal_first_start_has_nothing_to_drain(repo, monkeypatch):
    monkeypatch.setattr(folders, "_containers", lambda *args: [])
    monkeypatch.setattr(folders, "_drain_worker", lambda *args: pytest.fail("Unexpected drain"))
    folders.quiesce_for_start(repo)


def test_normal_restart_drains_and_checks_claims_before_compose_up(repo, monkeypatch):
    events = []
    monkeypatch.setattr(folders, "_containers", lambda *args: ["worker-id"])
    monkeypatch.setattr(folders, "_container_state", lambda *args: {"Running": True})
    monkeypatch.setattr(folders, "_drain_worker", lambda *args: events.append("drain"))
    monkeypatch.setattr(folders, "_assert_quiescent", lambda *args: events.append("quiescent"))
    folders.quiesce_for_start(repo)
    assert events == ["drain", "quiescent"]


def test_stopped_stack_restart_does_not_require_exec_into_a_stopped_api(repo, monkeypatch):
    events = []
    monkeypatch.setattr(folders, "_containers", lambda *args: ["stopped-id"])
    monkeypatch.setattr(folders, "_container_state", lambda *args: {
        "Running": False, "ExitCode": 0,
    })
    monkeypatch.setattr(folders, "_drain_worker", lambda *args: events.append("drain"))
    monkeypatch.setattr(folders, "_assert_quiescent", lambda *args: pytest.fail("API is stopped"))
    folders.quiesce_for_start(repo)
    assert events == ["drain"]


def test_live_legacy_worker_never_receives_usr1(repo, monkeypatch):
    monkeypatch.setattr(folders, "_containers", lambda *args: ["worker-id"])
    monkeypatch.setattr(folders, "_container_state", lambda *args: {"Running": True})
    calls = []

    def run(command, *args, **kwargs):
        calls.append(command)
        raise folders.FolderError(kwargs["error"])

    monkeypatch.setattr(folders, "_run", run)
    with pytest.raises(folders.FolderError, match="worker_drain_upgrade_required"):
        folders._drain_worker(repo)
    assert len(calls) == 1 and calls[0][:3] == ["docker", "exec", "worker-id"]


def test_multiple_workers_are_refused_before_any_signal(repo, monkeypatch):
    monkeypatch.setattr(folders, "_containers", lambda *args: ["worker-1", "worker-2"])
    monkeypatch.setattr(folders, "_run", lambda *args, **kwargs: pytest.fail("Signal sent"))
    with pytest.raises(folders.FolderError, match="single_worker_required"):
        folders._drain_worker(repo)


def test_worktree_bridge_lock_also_excludes_a_second_port(repo):
    with folders._instance_lock(repo):
        with pytest.raises(folders.FolderError, match="local_folder_bridge_already_running"):
            with folders._instance_lock(repo):
                pytest.fail("A second bridge acquired the same worktree")


@pytest.fixture
def bridge_http(repo):
    bridge = folders.Bridge(repo, {})
    server = folders.ThreadingHTTPServer(("127.0.0.1", 0), folders.handler_for(bridge))
    bridge.port = server.server_port
    thread = threading.Thread(
        target=server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True,
    )
    thread.start()
    yield bridge
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def request(bridge, method="GET", path="/status", *, headers=None, body=None):
    connection = http.client.HTTPConnection("127.0.0.1", bridge.port, timeout=2)
    try:
        connection.request(method, path, body=body, headers={
            "Origin": "http://127.0.0.1:3000", **(headers or {}),
        })
        response = connection.getresponse()
        payload = response.read()
        return (
            response.status, dict(response.getheaders()), json.loads(payload) if payload else None,
        )
    finally:
        connection.close()


@pytest.mark.parametrize("headers", [
    {"Origin": "https://attacker.example"},
    {"Origin": "null"},
    {"Origin": "http://127.0.0.1:3000.attacker.example"},
    {"Host": "attacker.example:8765"},
    {"Host": "attacker@localhost:8765"},
])
def test_status_rejects_foreign_browser_origins_and_host_rebinding(bridge_http, headers):
    status, _, body = request(bridge_http, headers=headers)
    assert status == 403
    assert "session_token" not in body


def test_mutations_require_session_and_reject_browser_supplied_host_paths(bridge_http, monkeypatch):
    monkeypatch.setattr(
        folders, "_native_selection", lambda *args: pytest.fail("Picker was called"),
    )
    status, headers, payload = request(bridge_http)
    assert status == 200 and payload["protocol"] == 1
    assert headers["Cache-Control"] == "no-store"
    body = json.dumps({"operation_id": str(uuid.uuid4())})
    assert request(bridge_http, "POST", "/folder-selections", body=body, headers={
        "Content-Type": "application/json",
    })[0] == 403
    assert request(bridge_http, "POST", "/folder-selections", body=json.dumps({
        "operation_id": str(uuid.uuid4()), "path": "C:\\private",
    }), headers={
        "Content-Type": "application/json", "X-FileTrace-Session": payload["session_token"],
    })[0] == 400
    assert not bridge_http.operations


def test_preflight_is_limited_to_allowed_browser_headers(bridge_http):
    status, headers, _ = request(bridge_http, "OPTIONS", "/folder-selections", headers={
        "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type,x-filetrace-session",
    })
    assert status == 204
    assert headers["Access-Control-Allow-Origin"] == "http://127.0.0.1:3000"
    assert request(bridge_http, "OPTIONS", "/folder-selections", headers={
        "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "x-other",
    })[0] == 403


def test_bridge_cannot_shutdown_while_it_owns_a_background_preparation(bridge_http):
    operation_id = str(uuid.uuid4())
    bridge_http.operations[operation_id] = {"operation_id": operation_id, "state": "waiting"}
    status, _, payload = request(bridge_http, "POST", "/shutdown", body="{}", headers={
        "Content-Type": "application/json", "X-FileTrace-Session": bridge_http.token,
    })
    assert status == 409 and payload["error_code"] == "operation_in_progress"
    assert not bridge_http.stopping


@pytest.mark.skipif(os.name != "nt", reason="Windows bridge console inheritance is platform-specific")
def test_changed_port_retires_this_worktrees_old_helper_before_spawning(repo, monkeypatch):
    folders._write_json(folders.state_dir(repo) / "bridge.instance.json", {"port": 8764})
    events = []
    started = []

    def probe(repo, config, *, port=None):
        if port == 8764:
            return {"session_token": "old-session"}
        return {"available": True} if started else None

    monkeypatch.setattr(folders, "_probe", probe)
    monkeypatch.setattr(folders, "_retire_bridge", lambda *args, **kwargs: events.append(kwargs))
    monkeypatch.setattr(
        folders.subprocess, "Popen",
        lambda command, **kwargs: started.append((command, kwargs)),
    )
    folders.ensure_bridge(repo, {})
    assert events == [{"port": 8764}]
    assert len(started) == 1
    assert "creationflags" not in started[0][1]


def test_probe_will_not_reuse_a_different_worktrees_bridge(bridge_http, tmp_path):
    with pytest.raises(folders.FolderError, match="local_folder_port_in_use"):
        folders._probe(tmp_path / "another-project", {
            "LOCAL_FOLDER_BRIDGE_PORT": str(bridge_http.port),
        })


def test_container_checks_are_not_imported_by_the_host_module():
    # Importing the helper is deliberately possible without host FastAPI,
    # SQLAlchemy, psycopg or any package from the Docker application runtime.
    assert "sqlalchemy" not in folders.__dict__
