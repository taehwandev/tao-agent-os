"""Canonical project-local storage for the continuation packet.

The packet is the one Tao record that may hold a bounded project fact, so its
location is not a convention but a checkable boundary: exactly one canonical
path per run, proven ignored by Git before it is accepted, written through a
private temporary file and an atomic rename so a process that dies mid-write
leaves the previous valid generation byte for byte intact.
"""

from __future__ import annotations

import json
import os
import stat
import subprocess
import uuid
from pathlib import Path
from typing import Any

from agent_continuation_fields import RUN_ID_RE, failure
from agent_continuation_packet import (
    CONTINUATION_FILENAME,
    MAX_PACKET_BYTES,
    ContinuationPacketError,
    canonical_packet_bytes,
    validate_continuation_packet,
)
from agent_workspace_policy import is_non_git_workspace


STATE_DIR = ".tao"
RUNS_DIR = "runs"


def continuation_path(project: Path, run_id: str) -> Path:
    """Return the only path a packet for this run may occupy."""

    return project.resolve() / STATE_DIR / RUNS_DIR / str(run_id) / CONTINUATION_FILENAME


def list_continuation_run_ids(project: Path) -> list[str]:
    """List run ids holding a packet file, without reading or trusting any."""

    runs = project.resolve() / STATE_DIR / RUNS_DIR
    if not runs.is_dir():
        return []
    return sorted(
        entry.name
        for entry in runs.iterdir()
        if RUN_ID_RE.match(entry.name) and (entry / CONTINUATION_FILENAME).is_file()
    )


def boundary_failures(project: Path, path: Path) -> list[dict[str, str]]:
    """Prove the canonical, symlink-free, Git-ignored local-only boundary.

    ``storage_class`` in the schema is a label. These checks are the proof: the
    path is the exact canonical one, no parent is a symlink that could redirect
    the write out of the project, and Git itself confirms the file is ignored
    rather than merely absent from the index.
    """

    failures: list[dict[str, str]] = []
    run_id = path.parent.name
    if not RUN_ID_RE.match(run_id):
        failures.append(failure("invalid_run_id", "/run_id"))
    elif path != continuation_path(project, run_id):
        failures.append(failure("path_not_canonical", ""))
    if any(parent.is_symlink() for parent in _guarded_parents(path)):
        failures.append(failure("symlinked_path", ""))
    if not _git_ignores(project, path):
        failures.append(failure("not_git_ignored", ""))
    return failures


def write_continuation_packet(project: Path, payload: dict[str, Any]) -> Path:
    """Validate, then replace the packet atomically; never write in place."""

    failures = validate_continuation_packet(payload)
    if failures:
        raise ContinuationPacketError(failures)
    path = continuation_path(project, str(payload["run_id"]))
    encoded = canonical_packet_bytes(payload)
    if len(encoded) > MAX_PACKET_BYTES:
        raise ContinuationPacketError([failure("packet_too_large", "")])
    _create_private_directory(path.parent)
    failures = boundary_failures(project, path)
    if failures:
        raise ContinuationPacketError(failures)
    _atomic_replace(path, encoded)
    return path


def read_continuation_packet(project: Path, path: Path) -> dict[str, Any]:
    """Return a packet only after its boundary, file, and schema all check out.

    Every refusal is reported by opaque run id and stable rule id. An invalid
    packet's prose is never returned, because prose that failed validation is
    exactly the prose no caller should render.
    """

    result: dict[str, Any] = {
        "run_id": path.parent.name,
        "status": "ok",
        "failures": [],
        "packet": None,
    }
    boundary = boundary_failures(project, path)
    if boundary:
        return _refused(result, "local_boundary_failed", boundary)
    file_failures = _file_failures(path)
    if file_failures:
        missing = file_failures[0]["rule"] == "missing_packet"
        return _refused(result, "not_found" if missing else "local_boundary_failed", file_failures)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _refused(result, "invalid_packet", [failure("unreadable_packet", "")])
    schema_failures = validate_continuation_packet(payload)
    if schema_failures:
        return _refused(result, "invalid_packet", schema_failures)
    if payload["run_id"] != path.parent.name:
        return _refused(result, "invalid_packet", [failure("run_binding_mismatch", "/run_id")])
    result["packet"] = payload
    return result


def _guarded_parents(path: Path) -> tuple[Path, ...]:
    """Return the packet and the three directories that could redirect it."""

    return (path, path.parent, path.parent.parent, path.parent.parent.parent)


def _refused(result: dict[str, Any], status: str, failures: list[dict[str, str]]) -> dict[str, Any]:
    result["status"] = status
    result["failures"] = failures
    result["packet"] = None
    return result


def _file_failures(path: Path) -> list[dict[str, str]]:
    try:
        info = path.lstat()
    except OSError:
        return [failure("missing_packet", "")]
    if not stat.S_ISREG(info.st_mode):
        return [failure("not_a_regular_file", "")]
    if info.st_nlink != 1:
        return [failure("unexpected_link_count", "")]
    if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
        return [failure("insecure_mode", "")]
    if info.st_size > MAX_PACKET_BYTES:
        return [failure("packet_too_large", "")]
    return []


def _create_private_directory(directory: Path) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(directory, 0o700)
    except OSError:
        pass


def _atomic_replace(path: Path, encoded: bytes) -> None:
    """Write a private temporary file, flush it, then replace the target.

    A crash before the rename leaves the previous packet untouched and no
    partially written target readable, which is the property that lets a
    checkpoint be trusted after a process death it never anticipated.
    """

    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            temporary.unlink()
        except OSError:
            pass
        raise
    _fsync_directory(path.parent)


def _fsync_directory(directory: Path) -> None:
    try:
        descriptor = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _git_ignores(project: Path, path: Path) -> bool:
    """Ask Git, not the filesystem, whether this exact path is local-only.

    A workspace with no repository keeps the equivalent policy: the shared
    workspace rules already classify the whole ``.tao`` state root as local-only,
    and no index exists that could accidentally publish the packet.
    """

    if is_non_git_workspace(project):
        return True
    try:
        completed = subprocess.run(
            ["git", "check-ignore", "-q", str(path)],
            cwd=project,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return completed.returncode == 0
