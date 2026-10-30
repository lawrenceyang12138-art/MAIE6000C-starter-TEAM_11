"""Start the real local stack with automatic dependency and model preparation.

This entry point needs only the Python standard library. Docker Desktop (or a
Docker daemon with Compose v2) is the one machine-level prerequisite; Python/AI
packages are installed inside the image, never into the user's Python process.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, build_opener

REPO = Path(__file__).resolve().parents[1]
BUILD_INPUTS = (
    "Dockerfile", ".dockerignore", "compose.yaml", "pyproject.toml", "README.md",
    "alembic.ini", "services", "scripts", "fixtures", "alembic", "tests", "frontend",
)
IGNORED_PARTS = {"node_modules", "dist", "__pycache__", ".pytest_cache", ".git", ".ruff_cache"}


class StartupError(RuntimeError):
    """An actionable, non-secret startup failure."""


def run(command: list[str], repo: Path, *, capture: bool = False) -> str:
    """Use argument lists, inherit build output, and never log environment values."""
    try:
        result = subprocess.run(
            command, cwd=repo, check=False, text=True,
            stdout=subprocess.PIPE if capture else None,
            stderr=subprocess.PIPE if capture else None,
        )
    except FileNotFoundError as exc:
        raise StartupError("Docker was not found. Install and start Docker Desktop first.") from exc
    if result.returncode:
        if command[1:2] == ["info"]:
            message = "Docker is not running. Start Docker Desktop and run this command again."
        else:
            message = "Docker command failed; inspect its output or run docker compose logs."
        raise StartupError(message)
    return result.stdout.strip() if capture else ""


def read_env(path: Path) -> dict[str, str]:
    """Read launcher-owned simple dotenv values, without executing shell syntax."""
    values = {}
    if not path.exists():
        return values
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
        values[key.strip()] = value
    return values


def prepare_env(repo: Path) -> dict[str, str]:
    """Create defaults exactly once; never overwrite an operator's existing .env."""
    destination = repo / ".env"
    if not destination.exists():
        try:
            with destination.open("xb") as stream:
                stream.write((repo / ".env.example").read_bytes())
        except FileExistsError:
            pass  # Another launcher won the create-only race.
        print("[configuration] Created .env from defaults; existing files are never replaced.")
    return read_env(destination)


def build_fingerprint(repo: Path, config: dict[str, str]) -> str:
    """Invalidate installed images only for build inputs, never model downloads."""
    digest = hashlib.sha256()
    for entry in BUILD_INPUTS:
        path = repo / entry
        files = sorted(path.rglob("*")) if path.is_dir() else [path]
        for file in files:
            relative = file.relative_to(repo)
            if any(part in IGNORED_PARTS for part in relative.parts):
                continue
            if file.is_symlink() or not file.is_file():
                continue
            digest.update(relative.as_posix().encode("utf-8"))
            digest.update(b"\0")
            with file.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
    # These are build arguments. Ordinary runtime configuration must not force a
    # reinstall; credentials and other .env values are neither stored nor printed.
    for key, default in (("FRONTEND_DATA_MODE", "api"), ("FRONTEND_API_BASE_URL", "/api")):
        digest.update(f"{key}={os.environ.get(key, config.get(key, default))}\n".encode())
    return digest.hexdigest()


def images_available(repo: Path) -> bool:
    try:
        # Unlike `compose images`, config image names exist even after `down`
        # removed all containers. A normal stop/start must not force a rebuild.
        images = sorted(set(run(
            ["docker", "compose", "config", "--images"], repo, capture=True,
        ).splitlines()))
        if not images:
            return False
        return bool(run(
            ["docker", "image", "inspect", *images, "--format", "{{.Id}}"], repo, capture=True,
        ))
    except StartupError:
        return False


def needs_build(repo: Path, fingerprint: str) -> bool:
    try:
        saved = json.loads((repo / "work/startup-build.json").read_text("utf-8"))
    except (OSError, ValueError):
        return True
    return saved.get("fingerprint") != fingerprint or not images_available(repo)


def write_build_marker(repo: Path, fingerprint: str) -> None:
    """Publish a complete cache marker even if two launchers finish together."""
    marker = repo / "work/startup-build.json"
    marker.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=marker.parent,
            prefix=".startup-build-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            json.dump({"fingerprint": fingerprint}, stream)
            stream.write("\n")
        os.replace(temporary, marker)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def local_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise StartupError("--api-url has an invalid host or port") from exc
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query or parsed.fragment
        or parsed.path not in {"", "/"}
        or port == 0
    ):
        raise StartupError("--api-url must be a local HTTP origin, e.g. http://127.0.0.1:8000")
    return value.rstrip("/")


def fetch_setup(api_url: str) -> dict:
    # Local preparation does not depend on machine-wide proxy settings.
    opener = build_opener(ProxyHandler({}))
    with opener.open(api_url + "/setup", timeout=5) as response:
        payload = json.load(response)
    if not isinstance(payload, dict) or not isinstance(payload.get("state"), str):
        raise ValueError("invalid preparation status")
    return payload


def status_line(status: dict) -> str:
    state = status.get("state", "unavailable")
    message = status.get("message", "Waiting for preparation status.")
    progress = status.get("stage_progress")
    percent = f" {progress:.1f}%" if isinstance(progress, (int, float)) else ""
    downloaded = status.get("downloaded_bytes")
    total = status.get("total_bytes")
    size = ""
    if state == "downloading" and isinstance(downloaded, (int, float)):
        size = f" ({downloaded / 1048576:.1f} MiB"
        if isinstance(total, (int, float)) and total > 0:
            size += f" / {total / 1048576:.1f} MiB"
        size += ")"
    return f"[{state}]{percent}{size} {message}"


def wait_for_model(api_url: str, timeout: float, interval: float = 1.0) -> int:
    deadline = time.monotonic() + timeout
    previous = None
    while time.monotonic() < deadline:
        try:
            status = fetch_setup(api_url)
        except (URLError, HTTPError, TimeoutError, OSError, ValueError):
            status = {"state": "unavailable", "message": "Waiting for the local API/AI service."}
        line = status_line(status)
        if line != previous:
            print(line, flush=True)
            previous = line
        if status.get("state") == "ready" and status.get("ready") is True:
            return 0
        if status.get("state") == "disabled":
            print("AI is explicitly disabled. Keyword search remains available.", flush=True)
            return 0
        if status.get("state") == "error":
            print(
                "Preparation failed. Keyword search remains available. Use Retry in the UI "
                "or POST /setup/retry after fixing the reported problem.", flush=True,
            )
            return 1
        time.sleep(min(interval, max(0, deadline - time.monotonic())))
    print(
        "Preparation wait timed out; services were left running. Check the UI progress, "
        "GET /setup or docker compose logs ai. This is not a model-ready result.", flush=True,
    )
    return 1


def main(argv: list[str] | None = None, *, repo: Path = REPO) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="check Docker without starting services",
    )
    parser.add_argument("--rebuild", action="store_true", help="build even if inputs are unchanged")
    parser.add_argument(
        "--no-wait", action="store_true", help="start without waiting for model readiness",
    )
    parser.add_argument(
        "--timeout", type=float, default=1800, help="model wait seconds (default: 1800)",
    )
    parser.add_argument("--api-url", help="local API HTTP origin; defaults to API_HOST_PORT")
    args = parser.parse_args(argv)
    if not math.isfinite(args.timeout) or args.timeout <= 0:
        parser.error("--timeout must be positive")
    try:
        print("[checking_environment] Checking Docker and Compose v2.", flush=True)
        run(["docker", "compose", "version", "--short"], repo, capture=True)
        run(["docker", "info", "--format", "{{.ServerVersion}}"], repo, capture=True)
        if args.check:
            print("Docker and Compose are available; no files or containers were changed.")
            return 0
        config = prepare_env(repo)
        mode = os.environ.get("FRONTEND_DATA_MODE", config.get("FRONTEND_DATA_MODE", "api"))
        if mode == "mock":
            print(
                "[configuration] Preserving explicit mock mode. The browser displays simulation, "
                "not real model progress. Set FRONTEND_DATA_MODE=api and restart to use the model."
            )
        port = os.environ.get("API_HOST_PORT", config.get("API_HOST_PORT", "8000"))
        api_url = local_url(args.api_url or f"http://127.0.0.1:{port}")
        fingerprint = build_fingerprint(repo, config)
        rebuild = args.rebuild or needs_build(repo, fingerprint)
        if rebuild:
            print(
                "[installing_dependencies] Building the runtime and UI. Docker installs "
                "the pinned Python/AI and Node packages; cached layers are reused.", flush=True,
            )
            run(["docker", "compose", "--progress", "plain", "build"], repo)
        else:
            print("[installing_dependencies] Reusing installed images; build inputs are unchanged.")
        run(["docker", "compose", "up", "-d", "--no-build"], repo)
        if rebuild:
            write_build_marker(repo, fingerprint)
        frontend_port = os.environ.get(
            "FRONTEND_HOST_PORT", config.get("FRONTEND_HOST_PORT", "3000"),
        )
        print(
            f"Open http://127.0.0.1:{frontend_port}/select to see preparation progress.",
            flush=True,
        )
        if args.no_wait:
            print("Services started; --no-wait does not assert model readiness. Check GET /setup.")
            return 0
        return wait_for_model(api_url, args.timeout)
    except StartupError as exc:
        print(f"Startup failed: {exc}", file=sys.stderr)
        return 1
    except OSError:
        print("Startup failed: a local configuration/build file could not be read or written.",
              file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Stopped waiting; any started services remain running.")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
