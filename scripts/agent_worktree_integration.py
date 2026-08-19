"""Verify lead-side result integration before removing a worker worktree."""

from __future__ import annotations

import hashlib
import os
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from agent_worktree_fingerprint import capture_worktree_state
from agent_worktree_identity import (
    WorktreeSessionError,
    validate_worker_worktree_identity,
    worktree_root,
)
from agent_worktree_session import remove_worker_worktree
from support.bounded_git import run_git


@dataclass(frozen=True)
class WorktreeFinalization:
    """Content-free summary of a verified lead-side finalization."""

    integrated_path_count: int
    discarded_ignored_path_count: int


def _git_paths(path: Path, *args: str) -> set[Path]:
    completed = run_git(
        ["git", "-C", str(path), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise WorktreeSessionError(
            f"cannot verify worker result integration: git {args[0]} failed"
        )
    paths: set[Path] = set()
    for record in completed.stdout.split(b"\0"):
        if not record:
            continue
        relative = Path(os.fsdecode(record))
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise WorktreeSessionError(
                "cannot verify worker result integration: unsafe Git path"
            )
        paths.add(relative)
    return paths


def _worker_changed_paths(worktree: Path) -> set[Path]:
    tracked = _git_paths(
        worktree,
        "diff",
        "--name-only",
        "-z",
        "--no-renames",
        "HEAD",
        "--",
    )
    untracked = _git_paths(
        worktree,
        "ls-files",
        "--others",
        "--exclude-standard",
        "-z",
        "--",
    )
    return tracked | untracked


def _worker_ignored_paths(worktree: Path) -> set[Path]:
    return _git_paths(
        worktree,
        "ls-files",
        "--others",
        "--ignored",
        "--exclude-standard",
        "-z",
        "--",
    )


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _materialized_state(root: Path, relative: Path) -> tuple[object, ...]:
    candidate = root / relative
    try:
        metadata = candidate.lstat()
    except FileNotFoundError:
        return ("missing",)
    if stat.S_ISLNK(metadata.st_mode):
        return ("symlink", os.readlink(candidate))
    if stat.S_ISREG(metadata.st_mode):
        return ("file", bool(metadata.st_mode & 0o111), _file_digest(candidate))
    raise WorktreeSessionError(
        "cannot verify worker result integration: unsupported changed path type"
    )


def _prune_admin_state(project: Path) -> None:
    completed = run_git(
        ["git", "-C", str(project), "worktree", "prune"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise WorktreeSessionError("cannot prune worker worktree admin state")
    try:
        worktree_root(project).rmdir()
    except FileNotFoundError:
        pass
    except OSError:
        # Other active worktrees or unrelated files keep the shared root alive.
        pass


def finalize_worker_worktree(
    project: Path,
    worktree_path: Path,
    *,
    discard_ignored: bool = False,
) -> WorktreeFinalization:
    """Remove a completed worker only after proving its result is integrated.

    The lead checkout must have the same materialized state for every tracked
    or untracked worker change. Ignored files are preserved by default because
    Git cannot establish whether they are disposable results; a lead may opt in
    to dropping them explicitly with ``discard_ignored=True``.
    """

    project = Path(project).expanduser().resolve()
    worktree = validate_worker_worktree_identity(project, worktree_path)
    before = capture_worktree_state(worktree)
    changed_paths = _worker_changed_paths(worktree)
    ignored_paths = _worker_ignored_paths(worktree)
    if ignored_paths and not discard_ignored:
        raise WorktreeSessionError(
            "ignored worker files require an explicit discard policy; "
            "worker worktree was preserved"
        )
    mismatches = sum(
        _materialized_state(worktree, relative)
        != _materialized_state(project, relative)
        for relative in changed_paths
    )
    if mismatches:
        raise WorktreeSessionError(
            f"worker result is not integrated into the lead checkout "
            f"({mismatches} path mismatch); worker worktree was preserved"
        )
    if capture_worktree_state(worktree) != before:
        raise WorktreeSessionError(
            "worker worktree changed during integration verification; "
            "worker worktree was preserved"
        )
    validate_worker_worktree_identity(project, worktree)
    if not remove_worker_worktree(
        project,
        worktree,
        force=bool(changed_paths or ignored_paths),
    ):
        raise WorktreeSessionError(
            "worker worktree disappeared before verified finalization completed"
        )
    _prune_admin_state(project)
    return WorktreeFinalization(
        integrated_path_count=len(changed_paths),
        discarded_ignored_path_count=len(ignored_paths),
    )
