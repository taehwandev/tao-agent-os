"""Bounded Git worktree fingerprints for execution-capsule bindings."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from pathlib import Path
from typing import Any, NamedTuple

from agent_worktree_scan import (
    UntrackedBudget,
    WorktreeFingerprintLimitExceeded,
    hash_component,
    hash_file_component,
    hash_git_component,
    visit_git_null_records,
)
from support.bounded_git import run_git


MAX_UNTRACKED_FILES = 5_000
MAX_UNTRACKED_BYTES = 256 * 1024 * 1024
MAX_CAPTURE_ATTEMPTS = 2


class WorktreeSnapshot(NamedTuple):
    """Two digests that always travel together, and never separately change.

    A frozen dataclass said the same thing, but `dataclasses` pulls `inspect`,
    and this module sits under the run registry that the pre-tool gate loads
    on every single tool call -- about 3 ms of import for two immutable
    strings. `typing` is already imported here, so this costs nothing new.
    """

    fingerprint: str
    signature: str


def git_output(path: Path, *args: str) -> str:
    completed = run_git(
        ["git", *args],
        cwd=path,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        if args == ("rev-parse", "--verify", "HEAD") and _unborn_head(path):
            return "unborn\n"
        raise RuntimeError(
            f"cannot capture git state for execution capsule: git {args[0]} failed"
        )
    return completed.stdout.decode("utf-8")


def _unborn_head(path: Path) -> bool:
    """Accept only a symbolic HEAD whose branch ref does not exist yet."""
    symbolic = run_git(
        ["git", "symbolic-ref", "-q", "HEAD"], cwd=path, check=False,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    if symbolic.returncode != 0:
        return False
    reference = symbolic.stdout.decode("utf-8").strip()
    if not reference.startswith("refs/heads/"):
        return False
    exists = run_git(
        ["git", "show-ref", "--verify", "--quiet", reference], cwd=path,
        check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    return exists.returncode == 1


def capture_worktree_state(path: Path) -> WorktreeSnapshot:
    """Capture the authoritative fingerprint and its cheap invalidation signature."""

    for _attempt in range(MAX_CAPTURE_ATTEMPTS):
        snapshot = _capture_worktree_state_once(path)
        if snapshot.signature == worktree_signature(path):
            return snapshot
    raise RuntimeError("worktree changed during execution-capsule fingerprint capture")


def _capture_worktree_state_once(path: Path) -> WorktreeSnapshot:
    """Capture one bounded snapshot; the public wrapper verifies its stability."""

    fingerprint = hashlib.sha256()
    signature = hashlib.sha256()
    budget = _new_budget()
    _capture_status(path, fingerprint, signature, budget)
    # Initial additions are content-hashed above. With no commit, diff against
    # the index for partial staging instead of asking Git for nonexistent HEAD.
    base = () if git_output(path, "rev-parse", "--verify", "HEAD").strip() == "unborn" else ("HEAD",)
    hash_git_component(
        fingerprint,
        b"working-tree",
        path,
        "diff",
        *base,
        "--binary",
        "--no-renames",
        "--diff-filter=a",
        "--no-ext-diff",
        "--no-textconv",
    )
    return WorktreeSnapshot(
        fingerprint=fingerprint.hexdigest(),
        signature=signature.hexdigest(),
    )


def worktree_fingerprint(path: Path) -> str:
    """Hash tracked and untracked state without persisting paths or contents."""

    return capture_worktree_state(path).fingerprint


def worktree_signature(path: Path) -> str:
    """Return a content-free invalidation filter for a prior strong fingerprint.

    The signature is never an identity proof on its own. Callers may reuse a
    previously captured strong fingerprint only while this signature and HEAD
    both match that prior record.
    """

    signature = hashlib.sha256()
    _capture_status(
        path,
        fingerprint=None,
        signature=signature,
        budget=_new_budget(),
    )
    return signature.hexdigest()


def _capture_status(
    path: Path,
    fingerprint: Any | None,
    signature: Any,
    budget: UntrackedBudget,
) -> None:
    expecting_original_path = False
    original_path_is_deleted = False
    entries: list[tuple[bytes, bytes, bool, bytes]] = []

    def visit(record: bytes) -> None:
        nonlocal expecting_original_path, original_path_is_deleted
        if expecting_original_path:
            expecting_original_path = False
            if original_path_is_deleted:
                entries.append((b"1", record, False, b""))
            original_path_is_deleted = False
            return

        kind, relative_bytes, renamed = _status_path(record)
        expecting_original_path = renamed
        original_path_is_deleted = renamed and _rename_removes_original(record)
        if relative_bytes is None:
            return
        if kind in {b"1", b"2"} and _dirty_submodule(record):
            raise RuntimeError(
                "dirty submodule state cannot be bound to an execution capsule"
            )
        xy = _status_xy(record)
        added_like = kind == b"?" or kind == b"2" or b"A" in xy
        entries.append((kind, relative_bytes, added_like, record))

    visit_git_null_records(
        path,
        ("status", "--porcelain=v2", "-z", "--untracked-files=all"),
        visit,
    )

    for relative_bytes in sorted(
        {relative for _kind, relative, _added, _record in entries}
    ):
        hash_component(signature, b"status-path", relative_bytes)
        if fingerprint is not None:
            hash_component(fingerprint, b"status-path", relative_bytes)

    for kind, relative_bytes, added_like, record in sorted(
        entries,
        key=lambda entry: entry[1],
    ):
        xy = _status_xy(record)
        if len(xy) == 2 and xy[0:1] != b"." and xy[1:2] != b".":
            hash_component(signature, b"partial-status", record)
            if fingerprint is not None:
                hash_component(fingerprint, b"partial-status", record)
        candidate = path / Path(os.fsdecode(relative_bytes))
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            hash_component(signature, b"worktree-raced", relative_bytes)
            if fingerprint is not None:
                hash_component(fingerprint, b"worktree-raced", relative_bytes)
            continue
        _hash_metadata(signature, relative_bytes, metadata)
        if not added_like:
            continue

        budget.add_file(metadata.st_size)
        if fingerprint is None:
            continue
        hash_component(fingerprint, b"added-path", relative_bytes)
        hash_component(
            fingerprint,
            b"added-mode",
            str(stat.S_IMODE(metadata.st_mode)).encode("ascii"),
        )
        if stat.S_ISLNK(metadata.st_mode):
            try:
                payload = os.fsencode(os.readlink(candidate))
            except FileNotFoundError:
                hash_component(fingerprint, b"added-raced", relative_bytes)
                continue
            budget.add_read_bytes(len(payload))
            hash_component(fingerprint, b"added-content", payload)
        elif stat.S_ISREG(metadata.st_mode):
            try:
                hash_file_component(
                    fingerprint,
                    b"added-content",
                    candidate,
                    budget,
                )
            except FileNotFoundError:
                hash_component(fingerprint, b"added-raced", relative_bytes)
        else:
            hash_component(
                fingerprint,
                b"added-content",
                str(metadata.st_mode).encode("ascii"),
            )


def _status_path(record: bytes) -> tuple[bytes, bytes | None, bool]:
    """Extract a porcelain-v2 path without decoding or retaining it."""

    kind = record[:1]
    if kind == b"?":
        return kind, record[2:], False
    if kind == b"1":
        fields = record.split(b" ", 8)
        return kind, fields[8] if len(fields) == 9 else None, False
    if kind == b"2":
        fields = record.split(b" ", 9)
        return kind, fields[9] if len(fields) == 10 else None, True
    if kind == b"u":
        fields = record.split(b" ", 10)
        return kind, fields[10] if len(fields) == 11 else None, False
    return kind, None, False


def _status_xy(record: bytes) -> bytes:
    """Return the porcelain-v2 XY field without retaining the full record."""

    kind = record[:1]
    if kind in {b"1", b"2", b"u"}:
        fields = record.split(b" ", 2)
        return fields[1] if len(fields) >= 2 else b""
    return b""


def _rename_removes_original(record: bytes) -> bool:
    """Return whether a porcelain-v2 kind-2 record represents a rename."""

    if record[:1] != b"2":
        return False
    fields = record.split(b" ", 9)
    return len(fields) == 10 and fields[8].startswith(b"R")


def _dirty_submodule(record: bytes) -> bool:
    fields = record.split(b" ", 3)
    return len(fields) >= 3 and fields[2].startswith(b"S") and fields[2] != b"S..."


def _new_budget() -> UntrackedBudget:
    return UntrackedBudget(MAX_UNTRACKED_FILES, MAX_UNTRACKED_BYTES)


def _hash_metadata(digest: Any, relative_bytes: bytes, metadata: os.stat_result) -> None:
    hash_component(digest, b"worktree-path", relative_bytes)
    values = (
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_dev,
        metadata.st_ino,
    )
    hash_component(
        digest,
        b"worktree-metadata",
        b"\0".join(str(value).encode("ascii") for value in values),
    )
