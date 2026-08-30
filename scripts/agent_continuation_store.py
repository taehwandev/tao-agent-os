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
from typing import Any, Optional, Union

from agent_continuation_fields import RUN_ID_RE, failure
from agent_continuation_packet import (
    CONTINUATION_FILENAME,
    MAX_PACKET_BYTES,
    ContinuationPacketError,
    canonical_packet_bytes,
    validate_continuation_packet,
)
from agent_workspace_policy import is_non_git_workspace
from support.bounded_git import run_git


STATE_DIR = ".tao"
RUNS_DIR = "runs"


def continuation_path(project: Path, run_id: str) -> Path:
    """Return the only path a packet for this run may occupy."""

    return project.resolve() / STATE_DIR / RUNS_DIR / str(run_id) / CONTINUATION_FILENAME


def list_continuation_run_ids(project: Path) -> list[str]:
    """List run ids holding a packet file, without reading or trusting any."""

    state = project.resolve() / STATE_DIR
    runs = state / RUNS_DIR
    if state.is_symlink() or runs.is_symlink() or not runs.is_dir():
        return []
    return sorted(
        entry.name
        for entry in runs.iterdir()
        if (
            RUN_ID_RE.match(entry.name)
            and not entry.is_symlink()
            and not (entry / CONTINUATION_FILENAME).is_symlink()
            and (entry / CONTINUATION_FILENAME).is_file()
        )
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
    failures = boundary_failures(project, path)
    if failures:
        raise ContinuationPacketError(failures)
    try:
        directory_fd = _open_private_run_directory(project.resolve(), str(payload["run_id"]))
    except OSError as error:
        raise ContinuationPacketError([failure("local_boundary_unavailable", "")]) from error
    try:
        failures = boundary_failures(project, path)
        if failures:
            raise ContinuationPacketError(failures)
        _atomic_replace(path, encoded, directory_fd)
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
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
    file_failures, encoded = _guarded_read(path)
    if file_failures:
        status = {
            "missing_packet": "not_found",
            "unreadable_packet": "invalid_packet",
        }.get(file_failures[0]["rule"], "local_boundary_failed")
        return _refused(result, status, file_failures)
    try:
        payload = json.loads(encoded.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
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


def _guarded_read(path: Path) -> tuple[list[dict[str, str]], bytes]:
    """Check and read one open file, so the bytes returned are the bytes checked.

    Validating a path and then reading it again by name leaves a window where
    the two can be different files. Everything here is decided from a single
    descriptor opened without following a symlink, so the inode that passed
    the mode and size rules is necessarily the inode whose bytes are parsed.

    Link count is deliberately not a rule. A second hard link cannot subvert
    this store: every write creates a fresh inode under ``O_EXCL`` and renames
    it over the name, so an extra link holds an orphaned older generation and
    never receives a write. It also cannot widen access, because the run
    directory is owner-only and the packet is ``0600`` -- anyone able to make
    the link could already open the canonical path. Meanwhile ordinary backup,
    sync, and indexing daemons do hold a durable second link to files in a
    user's home, which made the old rule refuse valid packets for as long as
    that link lived.
    """

    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return [failure("missing_packet", "")], b""
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode):
            return [failure("not_a_regular_file", "")], b""
        if os.name == "posix" and stat.S_IMODE(info.st_mode) & 0o077:
            return [failure("insecure_mode", "")], b""
        if info.st_size > MAX_PACKET_BYTES:
            return [failure("packet_too_large", "")], b""
        with os.fdopen(descriptor, "rb") as stream:
            descriptor = -1
            encoded = stream.read(MAX_PACKET_BYTES + 1)
    except OSError:
        return [failure("unreadable_packet", "")], b""
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    if len(encoded) > MAX_PACKET_BYTES:
        return [failure("packet_too_large", "")], b""
    return [], encoded


def _open_private_run_directory(project: Path, run_id: str) -> Optional[int]:
    """Create the local path without following a symlink at any component."""

    secure_dir_fd = (
        os.name == "posix"
        and os.open in os.supports_dir_fd
        and os.mkdir in os.supports_dir_fd
    )
    if not secure_dir_fd:
        directory = project / STATE_DIR / RUNS_DIR / run_id
        directory.mkdir(parents=True, exist_ok=True)
        try:
            os.chmod(directory, 0o700)
        except OSError:
            pass
        return None

    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open(project, flags)
    try:
        for name in (STATE_DIR, RUNS_DIR, run_id):
            try:
                os.mkdir(name, 0o700, dir_fd=descriptor)
            except FileExistsError:
                pass
            child = os.open(name, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        os.fchmod(descriptor, 0o700)
        result = descriptor
        descriptor = -1
        return result
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _atomic_replace(path: Path, encoded: bytes, directory_fd: Optional[int] = None) -> None:
    """Write a private temporary file, flush it, then replace the target.

    A crash before the rename leaves the previous packet untouched and no
    partially written target readable, which is the property that lets a
    checkpoint be trusted after a process death it never anticipated.
    """

    temporary_name = f".{path.name}.{uuid.uuid4().hex}.tmp"
    temporary = path.parent / temporary_name
    target: Union[str, Path] = path.name if directory_fd is not None else path
    candidate: Union[str, Path] = temporary_name if directory_fd is not None else temporary
    descriptor = os.open(
        candidate,
        os.O_WRONLY | os.O_CREAT | os.O_EXCL,
        0o600,
        dir_fd=directory_fd,
    )
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(encoded)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(
            candidate,
            target,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
    except BaseException:
        try:
            if directory_fd is None:
                temporary.unlink()
            else:
                os.unlink(temporary_name, dir_fd=directory_fd)
        except OSError:
            pass
        raise
    if directory_fd is None:
        _fsync_directory(path.parent)
    else:
        try:
            os.fsync(directory_fd)
        except OSError:
            pass


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
        completed = run_git(
            ["git", "check-ignore", "-q", str(path)],
            cwd=project,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False
    return completed.returncode == 0
