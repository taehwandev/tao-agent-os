"""Bounded fingerprints for Tao Agent OS roots outside Git."""

from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path
from typing import Any

from agent_worktree_fingerprint import WorktreeSnapshot
from agent_worktree_scan import (
    UntrackedBudget,
    hash_component,
    hash_file_component,
)


DIRECTORY_STATE_HEAD = "non-git-directory-v1"
MAX_DIRECTORY_FILES = 10_000
MAX_DIRECTORY_BYTES = 512 * 1024 * 1024
MAX_CAPTURE_ATTEMPTS = 2
EXCLUDED_DIRECTORY_NAMES = frozenset(
    {
        ".tao",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".vibeguard",
        ".wikimap",
        "__pycache__",
        "graphify-out",
        "node_modules",
    }
)
EXCLUDED_FILE_NAMES = frozenset({".DS_Store", ".coverage"})
EXCLUDED_FILE_SUFFIXES = frozenset({".log", ".pyc", ".pyo"})


def directory_state(
    path: Path,
    recorded: dict[str, str] | None = None,
) -> dict[str, str]:
    """Return a Git-shaped record for a bounded non-Git directory."""

    path = path.resolve()
    signature = directory_signature(path)
    if (
        _is_reusable_directory_state(recorded)
        and recorded["worktree_signature"] == signature
    ):
        return dict(recorded)

    snapshot = capture_directory_state(path)
    return {
        "head": DIRECTORY_STATE_HEAD,
        "worktree_fingerprint": snapshot.fingerprint,
        "worktree_signature": snapshot.signature,
    }


def capture_directory_state(path: Path) -> WorktreeSnapshot:
    """Capture a stable strong fingerprint without following symlinks."""

    for _attempt in range(MAX_CAPTURE_ATTEMPTS):
        snapshot = _capture_directory_state_once(path)
        if snapshot.signature == directory_signature(path):
            return snapshot
    raise RuntimeError(
        "directory changed during execution-capsule fingerprint capture"
    )


def directory_signature(path: Path) -> str:
    signature = hashlib.sha256()
    _visit_directory(
        root=path,
        current=path,
        fingerprint=None,
        signature=signature,
        budget=_new_budget(),
    )
    return signature.hexdigest()


def _capture_directory_state_once(path: Path) -> WorktreeSnapshot:
    fingerprint = hashlib.sha256()
    signature = hashlib.sha256()
    _visit_directory(
        root=path,
        current=path,
        fingerprint=fingerprint,
        signature=signature,
        budget=_new_budget(),
    )
    return WorktreeSnapshot(
        fingerprint=fingerprint.hexdigest(),
        signature=signature.hexdigest(),
    )


def _visit_directory(
    *,
    root: Path,
    current: Path,
    fingerprint: Any | None,
    signature: Any,
    budget: UntrackedBudget,
) -> None:
    try:
        with os.scandir(current) as stream:
            entries = sorted(stream, key=lambda entry: entry.name)
    except FileNotFoundError:
        hash_component(signature, b"directory-raced", os.fsencode(current.name))
        return

    for entry in entries:
        candidate = current / entry.name
        relative_bytes = os.fsencode(candidate.relative_to(root))
        try:
            metadata = entry.stat(follow_symlinks=False)
        except FileNotFoundError:
            hash_component(signature, b"directory-raced", relative_bytes)
            continue

        if stat.S_ISDIR(metadata.st_mode) and entry.name in EXCLUDED_DIRECTORY_NAMES:
            continue
        if stat.S_ISREG(metadata.st_mode) and _is_excluded_file(entry.name):
            continue

        _hash_signature_metadata(signature, relative_bytes, metadata)
        if stat.S_ISDIR(metadata.st_mode):
            _visit_directory(
                root=root,
                current=candidate,
                fingerprint=fingerprint,
                signature=signature,
                budget=budget,
            )
            continue

        budget.add_file(metadata.st_size)
        if fingerprint is None:
            continue
        hash_component(fingerprint, b"directory-path", relative_bytes)
        hash_component(
            fingerprint,
            b"directory-mode",
            str(stat.S_IMODE(metadata.st_mode)).encode("ascii"),
        )
        if stat.S_ISLNK(metadata.st_mode):
            try:
                target = os.fsencode(os.readlink(candidate))
            except FileNotFoundError:
                hash_component(fingerprint, b"directory-raced", relative_bytes)
                continue
            budget.add_read_bytes(len(target))
            hash_component(fingerprint, b"directory-symlink", target)
        elif stat.S_ISREG(metadata.st_mode):
            try:
                hash_file_component(
                    fingerprint,
                    b"directory-content",
                    candidate,
                    budget,
                )
            except FileNotFoundError:
                hash_component(fingerprint, b"directory-raced", relative_bytes)
        else:
            hash_component(
                fingerprint,
                b"directory-special",
                str(metadata.st_mode).encode("ascii"),
            )


def _hash_signature_metadata(
    signature: Any,
    relative_bytes: bytes,
    metadata: os.stat_result,
) -> None:
    hash_component(signature, b"directory-path", relative_bytes)
    values = (
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
        metadata.st_dev,
        metadata.st_ino,
    )
    hash_component(
        signature,
        b"directory-metadata",
        b"\0".join(str(value).encode("ascii") for value in values),
    )


def _is_excluded_file(name: str) -> bool:
    return (
        name in EXCLUDED_FILE_NAMES
        or Path(name).suffix in EXCLUDED_FILE_SUFFIXES
    )


def _new_budget() -> UntrackedBudget:
    return UntrackedBudget(MAX_DIRECTORY_FILES, MAX_DIRECTORY_BYTES)


def _is_reusable_directory_state(value: Any) -> bool:
    return (
        isinstance(value, dict)
        and value.get("head") == DIRECTORY_STATE_HEAD
        and _is_sha256(value.get("worktree_fingerprint"))
        and _is_sha256(value.get("worktree_signature"))
    )


def _is_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
