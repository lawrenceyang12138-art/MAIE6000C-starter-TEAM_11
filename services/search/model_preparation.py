"""Startup-only, resumable preparation of the public SHA-pinned local model.

Search/inference never downloads. Only startup or an explicit operator retry
calls this module. Unverified partial files are never published as model files.
"""

from __future__ import annotations

import hashlib
import errno
import json
import os
import re
import tempfile
from contextlib import contextmanager
from pathlib import Path
from threading import Event
from typing import Callable

import httpx

from services.search.text import (
    MODEL_FILE_BYTES,
    MODEL_FILES,
    MODEL_ID,
    MODEL_NAME,
    MODEL_REVISION,
    PINNED_MODEL_SHA256,
)

Progress = Callable[..., None]
BLOCK_BYTES = 1024 * 1024


class PreparationError(RuntimeError):
    """Only safe reason codes may leave the setup process."""


class PreparationCancelled(PreparationError):
    def __init__(self):
        super().__init__("preparation_cancelled")


def _cancelled(cancel: Event) -> None:
    if cancel.is_set():
        raise PreparationCancelled()


def _target(directory: Path, filename: str) -> Path:
    target = directory / filename
    if not target.resolve().is_relative_to(directory.resolve()):
        raise PreparationError("model_path_outside_storage")
    return target


@contextmanager
def _preparation_lock(directory: Path, cancel: Event, progress: Progress):
    """OS-owned lock: a crash releases it; a leftover filename is not a lock."""
    lock_path = _target(directory, ".prepare.lock")
    with lock_path.open("a+b") as stream:
        stream.seek(0, os.SEEK_END)
        if not stream.tell():
            stream.write(b"0")
            stream.flush()
        while True:
            _cancelled(cancel)
            try:
                if os.name == "nt":
                    import msvcrt

                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError as exc:
                if exc.errno not in {errno.EACCES, errno.EAGAIN, errno.EDEADLK}:
                    raise
                progress(state="checking_model", message="Waiting for model preparation lock.")
                cancel.wait(0.25)
        try:
            yield
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _digest(path: Path, cancel: Event, report: Callable[[int], None] | None = None) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(BLOCK_BYTES):
            _cancelled(cancel)
            checksum.update(block)
            if report:
                report(len(block))
    return checksum.hexdigest()


def _download_file(
    client: httpx.Client,
    directory: Path,
    filename: str,
    cancel: Event,
    timeout: float,
    retries: int,
    report: Callable[[int], None],
) -> None:
    target = _target(directory, filename)
    partial = _target(directory, filename + ".part")
    target.parent.mkdir(parents=True, exist_ok=True)
    expected_bytes = MODEL_FILE_BYTES[filename]
    expected_hash = PINNED_MODEL_SHA256[filename]
    # No mutable branch name, response-supplied filename or executable remote code.
    url = f"https://huggingface.co/{MODEL_NAME}/resolve/{MODEL_REVISION}/{filename}"
    reason = "model_download_failed"
    for attempt in range(retries):
        _cancelled(cancel)
        offset = partial.stat().st_size if partial.is_file() else 0
        if offset >= expected_bytes:
            if offset == expected_bytes and _digest(partial, cancel) == expected_hash:
                os.replace(partial, target)
                report(expected_bytes)
                return
            partial.unlink()
            offset = 0
        headers = {"Accept-Encoding": "identity", "User-Agent": "team11-local-model-setup/1"}
        if offset:
            headers["Range"] = f"bytes={offset}-"
        try:
            with client.stream("GET", url, headers=headers, timeout=timeout) as response:
                response.raise_for_status()
                if response.status_code == 206:
                    content_range = re.fullmatch(
                        r"bytes (\d+)-(\d+)/(\d+)", response.headers.get("content-range", "")
                    )
                    if (content_range is None or int(content_range[1]) != offset
                            or int(content_range[3]) != expected_bytes
                            or int(content_range[2]) != expected_bytes - 1):
                        raise PreparationError("model_download_invalid_range")
                elif response.status_code == 200:
                    offset = 0  # Server may ignore Range; never append a full response.
                else:
                    raise PreparationError("model_download_failed")
                report(offset)
                with partial.open("ab" if offset else "wb") as stream:
                    for block in response.iter_bytes(BLOCK_BYTES):
                        _cancelled(cancel)
                        if offset + len(block) > expected_bytes:
                            raise PreparationError("model_download_size_mismatch")
                        stream.write(block)
                        offset += len(block)
                        report(offset)
                    stream.flush()
                    os.fsync(stream.fileno())
            if offset != expected_bytes:
                raise PreparationError("model_download_size_mismatch")
            if _digest(partial, cancel) != expected_hash:
                partial.unlink()
                raise PreparationError("model_checksum_mismatch")
            os.replace(partial, target)
            return
        except PreparationCancelled:
            raise
        except (httpx.HTTPError, PreparationError) as exc:
            reason = str(exc) if isinstance(exc, PreparationError) else "model_download_failed"
            if attempt + 1 < retries:
                cancel.wait(min(2 ** attempt, 8))
    raise PreparationError(reason)


def _write_manifest(directory: Path) -> None:
    manifest = {"model": MODEL_ID, "revision": MODEL_REVISION, "sha256": PINNED_MODEL_SHA256}
    target = _target(directory, "model-manifest.json")
    descriptor, filename = tempfile.mkstemp(prefix=".manifest-", dir=directory)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            json.dump(manifest, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(filename, target)
    finally:
        Path(filename).unlink(missing_ok=True)


def prepare_local_model(
    directory: Path,
    *,
    progress: Progress,
    cancel: Event,
    allow_download: bool = True,
    timeout: float = 30,
    retries: int = 3,
) -> None:
    """Reuse verified files offline; repair only missing/corrupt pinned files."""
    if set(MODEL_FILES) != set(MODEL_FILE_BYTES) or set(MODEL_FILES) != set(PINNED_MODEL_SHA256):
        raise PreparationError("model_configuration_invalid")
    if any(os.environ.get(name, "").lower() in {"1", "true", "yes"}
           for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE")):
        allow_download = False
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with _preparation_lock(directory, cancel, progress):
            _prepare_locked(directory, progress, cancel, allow_download, timeout, retries)
    except PermissionError as exc:
        raise PreparationError("model_storage_unwritable") from exc
    except OSError as exc:
        raise PreparationError("model_storage_error") from exc


def _prepare_locked(directory, progress, cancel, allow_download, timeout, retries):
    total = sum(MODEL_FILE_BYTES.values())
    progress(state="checking_model", total_bytes=total, total_files=len(MODEL_FILES))
    good: set[str] = set()
    for filename in MODEL_FILES:
        _cancelled(cancel)
        target = _target(directory, filename)
        if (target.is_file() and target.stat().st_size == MODEL_FILE_BYTES[filename]
                and _digest(target, cancel) == PINNED_MODEL_SHA256[filename]):
            good.add(filename)
        progress(completed_files=len(good))
    completed = sum(MODEL_FILE_BYTES[filename] for filename in good)
    progress(downloaded_bytes=completed)
    if len(good) != len(MODEL_FILES):
        if not allow_download:
            raise PreparationError("local_model_missing_or_corrupt")
        progress(state="downloading", stage_progress=completed * 100 / total)
        with httpx.Client(follow_redirects=True) as client:
            for filename in MODEL_FILES:
                if filename in good:
                    continue

                def report(count: int) -> None:
                    progress(downloaded_bytes=completed + count,
                             stage_progress=(completed + count) * 100 / total)

                _download_file(client, directory, filename, cancel, timeout, retries, report)
                completed += MODEL_FILE_BYTES[filename]
                good.add(filename)
                progress(completed_files=len(good), downloaded_bytes=completed)
    progress(state="verifying", stage_progress=0)
    verified_bytes = 0

    def verified(count: int) -> None:
        nonlocal verified_bytes
        verified_bytes += count
        progress(stage_progress=verified_bytes * 100 / total)

    for filename in MODEL_FILES:
        _cancelled(cancel)
        target = _target(directory, filename)
        if (target.stat().st_size != MODEL_FILE_BYTES[filename]
                or _digest(target, cancel, verified) != PINNED_MODEL_SHA256[filename]):
            raise PreparationError("model_checksum_mismatch")
    _cancelled(cancel)
    _write_manifest(directory)
