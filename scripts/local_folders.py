"""Local folder consent bridge; the host process uses only Python's standard library.

The browser never supplies a filesystem path. A separate native chooser returns
one to this process, and only an explicit prepare request creates a read-only
Docker bind. Private paths and session tokens never enter HTTP access logs.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener
import uuid


PROTOCOL = 1
PICKER_TIMEOUT_SECONDS = 120
BUSY = {"selecting", "waiting", "preparing", "reconnecting"}
PUBLIC_FIELDS = {
    "operation_id", "state", "folder_name", "display_path", "mount_id", "error_code",
}


class FolderError(RuntimeError):
    """A stable, path-free folder setup failure."""


def state_dir(repo: Path) -> Path:
    return repo / "work" / "local-folders"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as exc:
        raise FolderError("local_folder_state_invalid") from exc


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


@contextmanager
def stack_lock(repo: Path):
    """Serialize launcher and bridge Docker/configuration operations across processes."""
    path = state_dir(repo) / "stack.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        if os.name == "nt":
            import msvcrt

            while True:
                try:
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.1)
            try:
                yield
            finally:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def compose_command(repo: Path, *args: str) -> list[str]:
    return [
        "docker", "compose", "--project-directory", str(repo),
        "-f", str(repo / "compose.yaml"),
        "-f", str(state_dir(repo) / "compose.sources.json"), *args,
    ]


def _value(config: dict, key: str, default: str) -> str:
    return os.environ.get(key, config.get(key, default))


def _configuration(repo: Path) -> dict:
    result = {}
    path = repo / ".env"
    if path.exists():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, separator, value = line.partition("=")
            if not separator:
                continue
            value = value.strip()
            if len(value) >= 2 and value[0] in "\"'" and value[-1] == value[0]:
                value = value[1:-1]
            else:
                value = value.split(" #", 1)[0].rstrip()
            result[key.strip()] = value
    return result


def _registry(repo: Path) -> dict:
    result = _read_json(state_dir(repo) / "registry.json", {"mounts": {}})
    if (
        not isinstance(result, dict) or not isinstance(result.get("mounts"), dict)
        or any(
            not isinstance(key, str) or not key.startswith("local-")
            or not isinstance(entry, dict) or not isinstance(entry.get("path"), str)
            for key, entry in result["mounts"].items()
        )
    ):
        raise FolderError("local_folder_state_invalid")
    return result


def _overlay(config: dict, registry: dict) -> dict:
    try:
        mounts = json.loads(_value(config, "SOURCE_MOUNTS", '{"corpus":"/source/corpus"}'))
    except ValueError as exc:
        raise FolderError("source_mounts_invalid") from exc
    if not isinstance(mounts, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in mounts.items()
    ):
        raise FolderError("source_mounts_invalid")
    volumes = []
    for mount_id, entry in registry["mounts"].items():
        target = "/source/local/" + mount_id
        if mount_id in mounts and mounts[mount_id] != target:
            raise FolderError("source_mount_id_conflict")
        mounts[mount_id] = target
        # Keep the mapping when a removable/deleted source disappears, but do
        # not ask Docker to manufacture a directory at the missing host path.
        try:
            available = Path(entry["path"]).is_dir()
        except OSError:
            available = False
        if available:
            volumes.append({
                "type": "bind", "source": entry["path"].replace("$", "$$"),
                "target": target, "read_only": True, "bind": {"create_host_path": False},
            })
    service = {
        "environment": {"SOURCE_MOUNTS": json.dumps(mounts).replace("$", "$$")},
        "volumes": volumes,
    }
    return {"services": {"api": service, "worker": service}}


def _run(command: list[str], repo: Path, *, error="docker_command_failed", timeout=180) -> str:
    try:
        options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
        result = subprocess.run(
            command, cwd=repo, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout, check=False, **options,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise FolderError(error) from exc
    if result.returncode:
        raise FolderError(error)
    return result.stdout.strip()


def _containers(repo: Path, service: str) -> list[str]:
    return _run(compose_command(repo, "ps", "--all", "--quiet", service), repo).split()


def _container_state(repo: Path, container: str) -> dict:
    try:
        return json.loads(_run([
            "docker", "inspect", container, "--format", "{{json .State}}",
        ], repo))
    except ValueError as exc:
        raise FolderError("container_status_invalid") from exc


def _worker_state(repo: Path, container: str) -> dict:
    try:
        return _container_state(repo, container)
    except FolderError:
        # An unavailable daemon is retryable, but an externally removed
        # container will never reappear under its old immutable ID.
        if container not in _containers(repo, "worker"):
            raise FolderError("worker_disappeared") from None
        raise


def _require_drain_support(repo: Path, container: str) -> None:
    # Check both the packaged protocol and the live PID 1 handler. A source
    # bind may have changed since an older worker process started; importing a
    # new class alone would not prove that USR1 is safe for that live process.
    code = (
        "import signal; from pathlib import Path; "
        "from services.worker.app.main import DrainRequest; "
        "caught=next(line.split()[1] for line in "
        "Path('/proc/1/status').read_text().splitlines() if line.startswith('SigCgt:')); "
        "raise SystemExit(0 if int(caught,16)&(1<<(signal.SIGUSR1-1)) else 1)"
    )
    _run(["docker", "exec", container, "python", "-c", code], repo,
         error="worker_drain_upgrade_required")


def _drain_worker(repo: Path, *, allow_missing=False, on_signal=None) -> None:
    containers = _containers(repo, "worker")
    if not containers and allow_missing:
        return
    if len(containers) != 1:
        raise FolderError("single_worker_required")
    container = containers[0]
    status = _container_state(repo, container)
    if status.get("Running"):
        _require_drain_support(repo, container)
        if on_signal:
            on_signal()
        while True:
            try:
                _run(["docker", "kill", "--signal=USR1", container], repo,
                     error="worker_drain_failed")
                break
            except FolderError:
                # A lost response can follow successful signal delivery. A
                # repeat USR1 only sets the same cooperative flag; never
                # abandon this worker or replace it with a stronger signal.
                try:
                    status = _worker_state(repo, container)
                    if not status.get("Running"):
                        break
                except FolderError as exc:
                    if str(exc) == "worker_disappeared":
                        raise
                time.sleep(1)
    while True:
        try:
            status = _worker_state(repo, container)
        except FolderError as exc:
            if str(exc) == "worker_disappeared":
                raise
            # A temporary Docker outage after consent to drain must not
            # abandon the worker that will eventually finish and exit.
            time.sleep(1)
            continue
        if not status.get("Running"):
            if status.get("ExitCode") != 0:
                raise FolderError("worker_abnormal_exit")
            return
        time.sleep(0.5)


def _assert_quiescent(repo: Path) -> None:
    _run(compose_command(
        repo, "exec", "-T", "api", "python", "scripts/local_folders.py", "--check-quiescent",
    ), repo, error="worker_not_quiescent")


def quiesce_for_start(repo: Path) -> None:
    """Finish a live worker's current job before any normal Compose upgrade.

    Call after ``prepare_sources`` and before ``compose up``, under the same
    stack lock. First starts have no worker and require no container check.
    """
    if not _containers(repo, "worker"):
        return
    _drain_worker(repo)
    api = _containers(repo, "api")
    if len(api) == 1 and _container_state(repo, api[0]).get("Running"):
        _assert_quiescent(repo)


def prepare_sources(repo: Path, config: dict) -> None:
    """Restore committed mounts. The caller must hold ``stack_lock``.

    An interrupted change is rolled back before the launcher can recreate any
    containers. Its durable selection remains available for an explicit retry.
    """
    directory = state_dir(repo)
    directory.mkdir(parents=True, exist_ok=True)
    registry = _registry(repo)
    operations = directory / "operations"
    alive = False
    try:
        with _instance_lock(repo):
            pass
    except FolderError:
        alive = True
    for path in operations.glob("*.json") if operations.exists() else []:
        operation = _read_json(path, {})
        if not isinstance(operation, dict):
            raise FolderError("local_folder_state_invalid")
        # A live chooser or a preparation thread waiting for this stack lock
        # still owns its journal. A normal repeat start is not a crash.
        if alive:
            continue
        if (
            operation.get("state") in {"waiting", "preparing", "reconnecting"}
            or operation.get("_rollback_pending")
        ):
            if operation.get("_drain_requested"):
                _drain_worker(repo, allow_missing=True)
            operation.update(
                state="failed", error_code="preparation_interrupted",
                _drain_requested=False, _rollback_pending=False,
            )
            _write_json(path, operation)
        elif operation.get("state") == "selecting":
            operation.update(state="failed", error_code="selection_interrupted")
            _write_json(path, operation)
    _write_json(directory / "compose.sources.json", _overlay(config, registry))


def project_id(repo: Path) -> str:
    return hashlib.sha256(os.path.normcase(str(repo.resolve())).encode()).hexdigest()[:24]


def _port(config: dict) -> int:
    try:
        port = int(_value(config, "LOCAL_FOLDER_BRIDGE_PORT", "8765"))
    except (TypeError, ValueError) as exc:
        raise FolderError("local_folder_port_invalid") from exc
    if not 1 <= port <= 65535:
        raise FolderError("local_folder_port_invalid")
    return port


def _origins(config: dict) -> set[str]:
    port = _value(config, "FRONTEND_HOST_PORT", "3000")
    return {
        f"http://{host}:{ui_port}"
        for host in ("localhost", "127.0.0.1") for ui_port in (port, "5173")
    }


def _configuration_id(config: dict) -> str:
    values = {
        key: _value(config, key, default) for key, default in (
            ("SOURCE_MOUNTS", '{"corpus":"/source/corpus"}'),
            ("LOCAL_FOLDER_BRIDGE_PORT", "8765"), ("FRONTEND_HOST_PORT", "3000"),
        )
    }
    values["implementation"] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    return hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()


def _interactive_python() -> Path:
    interpreter = Path(sys.executable)
    if interpreter.name.lower() == "pythonw.exe":
        interpreter = interpreter.with_name("python.exe")
    if not interpreter.is_file():
        raise FolderError("native_picker_unavailable")
    return interpreter


def _probe(repo: Path, config: dict, *, port: int | None = None) -> dict | None:
    request = Request(
        f"http://127.0.0.1:{port or _port(config)}/status",
        # The development origin remains allowed across frontend-port changes,
        # so the launcher can safely retire its own stale bridge instance.
        headers={"Origin": "http://127.0.0.1:5173"},
    )
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=0.5) as response:
            status = json.load(response)
    except HTTPError as exc:
        raise FolderError("local_folder_port_in_use") from exc
    except (URLError, TimeoutError, OSError):
        return None
    except ValueError as exc:
        raise FolderError("local_folder_port_in_use") from exc
    if (
        not isinstance(status, dict) or status.get("project_id") != project_id(repo)
        or status.get("protocol") != PROTOCOL or status.get("available") is not True
        or not isinstance(status.get("session_token"), str) or not status["session_token"]
    ):
        raise FolderError("local_folder_port_in_use")
    return status


@contextmanager
def _instance_lock(repo: Path):
    """One bridge per worktree, including when its configured port changes."""
    path = state_dir(repo) / "bridge.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as stream:
        stream.seek(0, 2)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise FolderError("local_folder_bridge_already_running") from exc
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == "nt":
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _retire_bridge(repo: Path, config: dict, status: dict, *, port: int | None = None) -> None:
    request = Request(
        f"http://127.0.0.1:{port or _port(config)}/shutdown", data=b"{}", method="POST",
        headers={
            "Origin": "http://127.0.0.1:5173", "Content-Type": "application/json",
            "X-FileTrace-Session": status["session_token"],
        },
    )
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=2) as response:
            response.read()
    except (OSError, URLError) as exc:
        raise FolderError("local_folder_configuration_busy") from exc
    for _ in range(50):
        if _probe(repo, config, port=port) is None:
            return
        time.sleep(0.1)
    raise FolderError("local_folder_configuration_busy")


def ensure_bridge(repo: Path, config: dict) -> None:
    """Start/reuse the bridge in the launcher's interactive Windows session."""
    if os.name != "nt":
        return
    metadata = _read_json(state_dir(repo) / "bridge.instance.json", {})
    if not isinstance(metadata, dict):
        raise FolderError("local_folder_state_invalid")
    old_port = metadata.get("port")
    if old_port and old_port != _port(config):
        old_config = {**config, "LOCAL_FOLDER_BRIDGE_PORT": str(old_port)}
        # The old port is explicit; do not let an environment override send a
        # shutdown request to an unrelated process on the new port.
        old_status = _probe(repo, old_config, port=old_port)
        if old_status:
            _retire_bridge(repo, old_config, old_status, port=old_port)
    status = _probe(repo, config)
    if status:
        if status.get("configuration_id") == _configuration_id(config):
            return
        _retire_bridge(repo, config, status)
    command = [
        sys.executable, str(repo / "scripts" / "local_folders.py"), "--serve",
        "--repo", str(repo), "--port", str(_port(config)),
        "--frontend-port", _value(config, "FRONTEND_HOST_PORT", "3000"),
    ]
    try:
        subprocess.Popen(
            command, cwd=repo, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, close_fds=True,
        )
    except OSError as exc:
        raise FolderError("local_folder_bridge_unavailable") from exc
    for _ in range(50):
        if _probe(repo, config):
            return
        time.sleep(0.1)
    raise FolderError("local_folder_bridge_unavailable")


def _picker_owner(user32, kernel32) -> int:
    """Use a visible foreground window, falling back to the launcher's console."""
    foreground = user32.GetForegroundWindow()
    if foreground and user32.IsWindow(foreground) and user32.IsWindowVisible(foreground):
        return foreground
    console = kernel32.GetConsoleWindow()
    if console and user32.IsWindow(console) and user32.IsWindowVisible(console):
        return console
    return 0


def _windows_shell_choose_folder() -> str | None:
    """Use the interactive Windows shell picker with a visible owner window."""
    import ctypes
    from ctypes import wintypes

    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_uint32), ("Data2", ctypes.c_uint16),
            ("Data3", ctypes.c_uint16), ("Data4", ctypes.c_ubyte * 8),
        ]

    def make_guid(value: str) -> GUID:
        return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)

    def check_hresult(result: int) -> None:
        if result < 0:
            raise OSError(f"Windows folder picker failed: 0x{result & 0xFFFFFFFF:08X}")

    ole32 = ctypes.OleDLL("ole32")
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    ole32.CoInitializeEx.argtypes = [ctypes.c_void_p, wintypes.DWORD]
    ole32.CoInitializeEx.restype = ctypes.c_long
    ole32.CoCreateInstance.argtypes = [
        ctypes.POINTER(GUID), ctypes.c_void_p, wintypes.DWORD,
        ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p),
    ]
    ole32.CoCreateInstance.restype = ctypes.c_long
    ole32.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole32.CoTaskMemFree.restype = None
    ole32.CoUninitialize.argtypes = []
    ole32.CoUninitialize.restype = None
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    kernel32.GetConsoleWindow.argtypes = []
    kernel32.GetConsoleWindow.restype = wintypes.HWND
    user32.IsWindow.argtypes = [wintypes.HWND]
    user32.IsWindow.restype = wintypes.BOOL
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL

    clsid_file_open_dialog = make_guid("DC1C5A9C-E88A-4DDE-A5A1-60F82A20AEF7")
    iid_file_dialog = make_guid("42F85136-DB7E-439C-85F1-E4075D135FC8")
    dialog = ctypes.c_void_p()
    initialized = False
    shell_item = ctypes.c_void_p()
    display_path = ctypes.c_wchar_p()
    try:
        result = ole32.CoInitializeEx(None, 0x2)  # COINIT_APARTMENTTHREADED
        check_hresult(result)
        initialized = True
        check_hresult(ole32.CoCreateInstance(
            ctypes.byref(clsid_file_open_dialog), None, 0x1,
            ctypes.byref(iid_file_dialog), ctypes.byref(dialog),
        ))  # CLSCTX_INPROC_SERVER

        def method(interface, index: int, result_type, argument_types):
            vtable = ctypes.cast(
                interface, ctypes.POINTER(ctypes.POINTER(ctypes.c_void_p)),
            ).contents
            prototype = ctypes.WINFUNCTYPE(result_type, ctypes.c_void_p, *argument_types)
            return prototype(vtable[index])

        options = wintypes.DWORD()
        check_hresult(method(dialog, 10, ctypes.c_long, [ctypes.POINTER(wintypes.DWORD)])(
            dialog, ctypes.byref(options),
        ))  # IFileDialog.GetOptions
        folder_options = options.value | 0x20 | 0x40 | 0x800 | 0x8
        check_hresult(method(dialog, 9, ctypes.c_long, [wintypes.DWORD])(
            dialog, folder_options,
        ))  # PICKFOLDERS | FORCEFILESYSTEM | PATHMUSTEXIST | NOCHANGEDIR
        check_hresult(method(dialog, 17, ctypes.c_long, [wintypes.LPCWSTR])(
            dialog, "Choose a folder for FileTrace (read-only)",
        ))  # IFileDialog.SetTitle
        result = method(dialog, 3, ctypes.c_long, [wintypes.HWND])(
            dialog, _picker_owner(user32, kernel32),
        )  # IFileDialog.Show
        if result & 0xFFFFFFFF == 0x800704C7:  # ERROR_CANCELLED
            return None
        check_hresult(result)
        check_hresult(method(dialog, 20, ctypes.c_long, [ctypes.POINTER(ctypes.c_void_p)])(
            dialog, ctypes.byref(shell_item),
        ))  # IFileDialog.GetResult

        check_hresult(method(
            shell_item, 5, ctypes.c_long,
            [wintypes.DWORD, ctypes.POINTER(ctypes.c_wchar_p)],
        )(shell_item, 0x80058000, ctypes.byref(display_path)))  # SIGDN_FILESYSPATH
        if not display_path.value:
            raise OSError("Windows folder picker returned no filesystem path")
        return display_path.value
    finally:
        if display_path:
            ole32.CoTaskMemFree(ctypes.cast(display_path, ctypes.c_void_p))
        if shell_item:
            method(shell_item, 2, None, [])(shell_item)  # IUnknown.Release
        if dialog:
            method(dialog, 2, None, [])(dialog)
        if initialized:
            ole32.CoUninitialize()


def choose_folder() -> str | None:
    """Run only in an independent process, never a threaded HTTP handler."""
    if os.name == "nt":
        return _windows_shell_choose_folder()

    import tkinter
    from tkinter import filedialog

    root = tkinter.Tk()
    root.title("FileTrace")
    root.geometry(f"1x1+{root.winfo_screenwidth() // 2}+{root.winfo_screenheight() // 2}")
    root.attributes("-topmost", True)
    if os.name == "nt":
        root.attributes("-toolwindow", True)
        root.attributes("-alpha", 0.01)
    root.deiconify()
    root.update()
    root.lift()
    root.focus_force()
    try:
        return filedialog.askdirectory(
            parent=root, title="Choose a folder for FileTrace (read-only)", mustexist=True,
        ) or None
    finally:
        root.destroy()


def _native_selection(repo: Path) -> str | None:
    if os.name == "nt":
        # Reuse the launcher's console session so Windows presents the modal
        # Shell dialog on the same interactive desktop without another console.
        interpreter = str(_interactive_python())
    else:
        interpreter = sys.executable
    command = [interpreter, str(Path(__file__).resolve()), "--choose-folder"]
    try:
        result = subprocess.run(
            command, cwd=repo, capture_output=True, text=True, encoding="utf-8",
            errors="replace", check=False, timeout=PICKER_TIMEOUT_SECONDS,
        )
        if result.returncode:
            raise FolderError("native_picker_unavailable")
        path = json.loads(result.stdout)
        if path is not None and not isinstance(path, str):
            raise ValueError
        return path
    except subprocess.TimeoutExpired as exc:
        raise FolderError("native_picker_timeout") from exc
    except (OSError, ValueError) as exc:
        raise FolderError("native_picker_unavailable") from exc


def _canonical_folder(value: str) -> Path:
    try:
        path = Path(value).resolve(strict=True)
        if not path.is_dir():
            raise OSError
        with os.scandir(path) as entries:
            next(entries, None)
        return path
    except OSError as exc:
        raise FolderError("folder_unavailable") from exc


class Bridge:
    def __init__(self, repo: Path, config: dict):
        self.repo = repo.resolve()
        self.config = config
        self.port = _port(config)
        self.origins = _origins(config)
        self.token = secrets.token_urlsafe(32)
        self.configuration_id = _configuration_id(config)
        self.stopping = False
        self._lock = threading.RLock()
        directory = state_dir(repo) / "operations"
        self.operations = {
            path.stem: _read_json(path, {}) for path in directory.glob("*.json")
        } if directory.exists() else {}

    def _save(self, operation: dict) -> None:
        _write_json(
            state_dir(self.repo) / "operations" / (operation["operation_id"] + ".json"),
            operation,
        )

    def _update(self, operation_id: str, **values) -> None:
        with self._lock:
            self.operations[operation_id].update(values)
            self._save(self.operations[operation_id])

    def get(self, operation_id: str) -> dict:
        with self._lock:
            operation = self.operations.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)
            return {key: value for key, value in operation.items() if key in PUBLIC_FIELDS}

    def select(self, operation_id: str) -> dict:
        with self._lock:
            if self.stopping:
                raise FolderError("bridge_restarting")
            if operation_id in self.operations:
                return self.get(operation_id)
            if any(value.get("state") in BUSY for value in self.operations.values()):
                raise FolderError("operation_in_progress")
            self.operations[operation_id] = {"operation_id": operation_id, "state": "selecting"}
            self._save(self.operations[operation_id])
            threading.Thread(target=self._select, args=(operation_id,), daemon=True).start()
            return self.get(operation_id)

    def _select(self, operation_id: str) -> None:
        try:
            selected = _native_selection(self.repo)
            if selected is None:
                self._update(operation_id, state="cancelled")
                return
            path = _canonical_folder(selected)
            self._update(
                operation_id, state="selected", folder_name=path.name or str(path),
                display_path=str(path), _path=str(path),
            )
        except (FolderError, OSError) as exc:
            self._update(
                operation_id, state="failed",
                error_code=str(exc) if isinstance(exc, FolderError) else "folder_unavailable",
            )

    def prepare(self, operation_id: str) -> dict:
        with self._lock:
            if self.stopping:
                raise FolderError("bridge_restarting")
            operation = self.operations.get(operation_id)
            if operation is None:
                raise KeyError(operation_id)
            if operation["state"] in {"waiting", "preparing", "reconnecting", "ready"}:
                return self.get(operation_id)
            if operation["state"] not in {"selected", "failed"} or "_path" not in operation:
                raise FolderError("selection_not_ready")
            if any(
                key != operation_id and value.get("state") in BUSY
                for key, value in self.operations.items()
            ):
                raise FolderError("operation_in_progress")
            operation.update(state="waiting")
            operation.pop("error_code", None)
            self._save(operation)
            threading.Thread(target=self._prepare, args=(operation_id,), daemon=True).start()
            return self.get(operation_id)

    def _wait_api(self) -> None:
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            containers = _containers(self.repo, "api")
            if len(containers) == 1:
                state = _container_state(self.repo, containers[0])
                if state.get("Running") and state.get("Health", {}).get("Status") == "healthy":
                    return
            time.sleep(0.5)
        raise FolderError("api_reconnect_failed")

    def _up(self) -> None:
        _run(compose_command(
            self.repo, "up", "-d", "--no-build", "--no-deps", "api",
        ), self.repo, error="api_reconnect_failed")
        self._wait_api()
        _run(compose_command(
            self.repo, "up", "-d", "--no-build", "--no-deps", "worker",
        ), self.repo, error="worker_reconnect_failed")

    def _check_quiescent(self) -> None:
        _assert_quiescent(self.repo)

    def _check_mount(self, mount_id: str) -> None:
        for service in ("api", "worker"):
            _run(compose_command(
                self.repo, "exec", "-T", service, "python", "scripts/local_folders.py",
                "--check-source", mount_id,
            ), self.repo, error="source_mount_unavailable")

    def _prepare(self, operation_id: str) -> None:
        with stack_lock(self.repo):
            registry = None
            source_config = self.config
            overlay_path = state_dir(self.repo) / "compose.sources.json"
            changed = False
            drained = False
            try:
                source_config = {**self.config, **_configuration(self.repo)}
                registry = _registry(self.repo)
                path = _canonical_folder(self.operations[operation_id]["_path"])
                mount_id = next((
                    key for key, value in registry["mounts"].items()
                    if os.path.normcase(value["path"]) == os.path.normcase(str(path))
                ), None)
                if mount_id is not None:
                    try:
                        self._check_mount(mount_id)
                    except FolderError:
                        pass  # A removable source may have returned since startup.
                    else:
                        self._update(operation_id, state="ready", mount_id=mount_id)
                        return
                mount_id = mount_id or "local-" + uuid.uuid4().hex
                candidate = json.loads(json.dumps(registry))
                candidate["mounts"][mount_id] = {"path": str(path), "folder_name": path.name}
                self._update(operation_id, mount_id=mount_id)
                _drain_worker(
                    self.repo,
                    on_signal=lambda: self._update(operation_id, _drain_requested=True),
                )
                drained = True
                self._check_quiescent()
                self._update(operation_id, state="preparing")
                _write_json(overlay_path, _overlay(source_config, candidate))
                changed = True
                _run(compose_command(self.repo, "config", "--quiet"), self.repo,
                     error="source_configuration_invalid")
                self._update(operation_id, state="reconnecting")
                self._up()
                self._check_mount(mount_id)
                _write_json(state_dir(self.repo) / "registry.json", candidate)
                self._update(operation_id, state="ready", _drain_requested=False)
            except (FolderError, OSError) as exc:
                error_code = (
                    str(exc) if isinstance(exc, FolderError) else "local_folder_state_unwritable"
                )
                rollback_pending = False
                if changed or drained:
                    try:
                        # Restore the durable recipe even if Docker itself
                        # cannot currently reconnect. Changing the recipe
                        # does not interrupt a container already running.
                        _write_json(overlay_path, _overlay(source_config, registry))
                        _write_json(state_dir(self.repo) / "registry.json", registry)
                        # A newly started worker may already be handling a
                        # queued job. Rollback has the same drain obligation.
                        _drain_worker(self.repo, allow_missing=True)
                        self._up()
                    except (FolderError, OSError):
                        error_code = "source_rollback_failed"
                        rollback_pending = True
                self._update(
                    operation_id, state="failed", error_code=error_code,
                    _rollback_pending=rollback_pending,
                    _drain_requested=rollback_pending,
                )


def handler_for(bridge: Bridge):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _respond(self, status: int, payload: dict) -> None:
            content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            origin = self.headers.get("Origin")
            if origin in bridge.origins:
                self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _authorized(self, *, session=True) -> bool:
            hosts = self.headers.get_all("Host", [])
            origins = self.headers.get_all("Origin", [])
            try:
                host = urlsplit("//" + hosts[0]) if len(hosts) == 1 else None
                valid = (
                    host is not None and host.hostname in {"127.0.0.1", "localhost"}
                    and host.port == bridge.port and host.username is None
                    and host.password is None and not host.path and not host.query
                    and not host.fragment and len(origins) == 1 and origins[0] in bridge.origins
                )
            except ValueError:
                valid = False
            if not valid:
                self._discard_body()
                self._respond(403, {"error_code": "origin_not_allowed"})
                return False
            tokens = self.headers.get_all("X-FileTrace-Session", [])
            if session and (len(tokens) != 1 or not hmac.compare_digest(tokens[0], bridge.token)):
                self._discard_body()
                self._respond(403, {"error_code": "invalid_session"})
                return False
            return True

        def _discard_body(self) -> None:
            # Closing a Windows socket with an unread small POST body may
            # reset the connection before the browser receives its refusal.
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if self.command == "POST" and 0 < length <= 4096:
                    self.connection.settimeout(2)
                    self.rfile.read(length)
            except (ValueError, OSError):
                pass

        def do_OPTIONS(self):
            if not self._authorized(session=False):
                return
            requested = {
                value.strip().lower()
                for value in self.headers.get("Access-Control-Request-Headers", "").split(",")
                if value.strip()
            }
            if (
                self.headers.get("Access-Control-Request-Method") not in {"GET", "POST"}
                or not requested <= {"content-type", "x-filetrace-session"}
            ):
                self._respond(403, {"error_code": "origin_not_allowed"})
                return
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", self.headers["Origin"])
            self.send_header("Access-Control-Allow-Methods", "GET, POST")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-FileTrace-Session")
            self.send_header("Vary", "Origin")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self):
            if not self._authorized(session=self.path != "/status"):
                return
            if self.path == "/status":
                self._respond(200, {
                    "available": True, "protocol": PROTOCOL,
                    "project_id": project_id(bridge.repo), "session_token": bridge.token,
                    "configuration_id": bridge.configuration_id,
                })
                return
            operation_id = self._operation_id() if len(self.path.split("/")) == 3 else None
            if operation_id is None:
                self._respond(404, {"error_code": "not_found"})
                return
            try:
                self._respond(200, bridge.get(operation_id))
            except KeyError:
                self._respond(404, {"error_code": "operation_not_found"})

        def _operation_id(self) -> str | None:
            parts = self.path.split("/")
            if len(parts) not in {3, 4} or parts[1] != "folder-selections":
                return None
            try:
                return parts[2] if str(uuid.UUID(parts[2])) == parts[2] else None
            except ValueError:
                return None

        def do_POST(self):
            if not self._authorized():
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if (
                    not 0 < length <= 4096
                    or self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json"
                    or self.headers.get("Transfer-Encoding")
                ):
                    raise ValueError
                body = json.loads(self.rfile.read(length))
                if self.path == "/shutdown":
                    if body != {}:
                        raise ValueError
                    with bridge._lock:
                        if any(value.get("state") in BUSY for value in bridge.operations.values()):
                            raise FolderError("operation_in_progress")
                        bridge.stopping = True
                    self._respond(200, {"stopping": True})
                    threading.Thread(target=self.server.shutdown, daemon=True).start()
                elif self.path == "/folder-selections":
                    if not isinstance(body, dict) or set(body) != {"operation_id"}:
                        raise ValueError
                    operation_id = body["operation_id"]
                    if (
                        not isinstance(operation_id, str)
                        or str(uuid.UUID(operation_id)) != operation_id
                    ):
                        raise ValueError
                    self._respond(202, bridge.select(operation_id))
                elif self.path.endswith("/prepare") and self._operation_id() is not None:
                    if body != {}:
                        raise ValueError
                    self._respond(202, bridge.prepare(self._operation_id()))
                else:
                    self._respond(404, {"error_code": "not_found"})
            except (ValueError, TypeError):
                self._respond(400, {"error_code": "invalid_request"})
            except KeyError:
                self._respond(404, {"error_code": "operation_not_found"})
            except FolderError as exc:
                self._respond(409, {"error_code": str(exc)})

    return Handler


def _container_check(*, mount_id: str | None) -> int:
    # These dependencies are deliberately imported only for the container CLI.
    if mount_id is not None:
        from services.common.config import get_settings

        path = get_settings().source_mounts.get(mount_id)
        if not path:
            return 1
        try:
            with os.scandir(path) as entries:
                next(entries, None)
            return 0
        except OSError:
            return 1
    from sqlalchemy import func, select
    from services.common.db import get_session_factory
    from services.common.models import Job, JobStatus

    with get_session_factory()() as db:
        count = db.scalar(select(func.count()).select_from(Job).where(
            Job.status == JobStatus.CLAIMED.value,
        ))
    return 0 if count == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--choose-folder", action="store_true")
    parser.add_argument("--check-quiescent", action="store_true")
    parser.add_argument("--check-source")
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--port")
    parser.add_argument("--frontend-port")
    args = parser.parse_args(argv)
    if args.check_quiescent or args.check_source:
        return _container_check(mount_id=args.check_source)
    if args.choose_folder:
        try:
            print(json.dumps(choose_folder(), ensure_ascii=True))
            return 0
        except Exception:
            return 1
    if not args.serve:
        parser.error("choose --serve, --choose-folder, or a container check")
    config = _configuration(args.repo)
    if args.port:
        config["LOCAL_FOLDER_BRIDGE_PORT"] = args.port
    if args.frontend_port:
        config["FRONTEND_HOST_PORT"] = args.frontend_port
    try:
        with _instance_lock(args.repo):
            bridge = Bridge(args.repo, config)
            server = ThreadingHTTPServer(("127.0.0.1", bridge.port), handler_for(bridge))
            server.daemon_threads = True
            _write_json(state_dir(args.repo) / "bridge.instance.json", {"port": bridge.port})
            try:
                server.serve_forever()
            finally:
                server.server_close()
                (state_dir(args.repo) / "bridge.instance.json").unlink(missing_ok=True)
    except (OSError, FolderError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
