"""Fail-closed git worktree lifecycle for isolated dispatch workers.

Overlapping ``owned_scope`` between concurrent writers is only safe when each
writer works inside its own real git worktree. This module creates and removes
those worktrees. Setup is fail-closed: when ``git worktree add`` cannot produce
a real isolated tree it raises, so a worker is never silently bound back to the
shared checkout.
"""

from __future__ import annotations

import subprocess
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from agent_worktree_identity import (
    WorktreeSessionError,
    generated_worker_path,
    validate_worker_worktree_identity,
)
from agent_worktree_fingerprint import WorktreeSnapshot, capture_worktree_state
from support.bounded_git import run_git

try:  # pragma: no cover - platform guard
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX platforms
    fcntl = None  # type: ignore[assignment]


LOCK_FILENAME = "worktree-session.lock"
MAX_CREATE_ATTEMPTS = 5
RETRY_DELAY_SECONDS = 0.1
_TRANSIENT_LOCK_MARKERS = ("index.lock", "cannot lock", "unable to create")


@contextmanager
def _creation_lock(project: Path) -> Iterator[None]:
    """Serialize worktree mutations to avoid ``.git/index.lock`` races.

    The lock is a best-effort process-level ``flock``. On platforms without
    ``fcntl`` the lock file is still created and the bounded retry loop remains
    the fallback against contention.
    """

    lock_dir = Path(project) / ".tao"
    lock_dir.mkdir(parents=True, exist_ok=True)
    lock_path = lock_dir / LOCK_FILENAME
    handle = open(lock_path, "w", encoding="ascii")
    try:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _is_transient_lock_error(stderr: str) -> bool:
    lowered = stderr.lower()
    return any(marker in lowered for marker in _TRANSIENT_LOCK_MARKERS)


def create_worker_worktree(
    project: Path, base_ref: str, worktree_path: Path
) -> WorktreeSnapshot:
    """Create a detached worker worktree at ``worktree_path`` from ``base_ref``.

    Fail-closed: any non-zero ``git worktree add`` raises ``WorktreeSessionError``
    and the shared checkout is never returned as a fallback. Returns the
    fingerprint of the freshly created worktree.
    """

    project = Path(project).expanduser().resolve()
    worktree_path = generated_worker_path(project, worktree_path)
    if not str(base_ref or "").strip():
        raise WorktreeSessionError("base_ref must be a non-empty git ref")
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    last_error = ""
    with _creation_lock(project):
        for attempt in range(MAX_CREATE_ATTEMPTS):
            completed = subprocess.run(
                [
                    "git",
                    "-C",
                    str(project),
                    "worktree",
                    "add",
                    "--detach",
                    str(worktree_path),
                    str(base_ref),
                ],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            if completed.returncode == 0:
                verified_path = validate_worker_worktree_identity(
                    project, worktree_path
                )
                try:
                    return capture_worktree_state(verified_path)
                except RuntimeError as error:
                    raise WorktreeSessionError(
                        "created worker worktree failed fingerprint validation"
                    ) from error
            last_error = completed.stderr.decode("utf-8", "replace").strip()
            if attempt < MAX_CREATE_ATTEMPTS - 1 and _is_transient_lock_error(last_error):
                time.sleep(RETRY_DELAY_SECONDS)
                continue
            break
    raise WorktreeSessionError(
        "cannot create isolated worker worktree: git worktree add failed"
        + (f" ({last_error})" if last_error else "")
    )


def remove_worker_worktree(
    project: Path, worktree_path: Path, *, force: bool = False
) -> bool:
    """Remove a worker worktree, pruning stale admin state.

    Idempotent-ish: if the worktree directory is already gone the admin records
    are pruned and ``False`` is reported rather than raising. Fail-closed: a
    plain ``git worktree remove`` that git rejects (for example a dirty worktree
    with unmerged work) raises rather than silently retrying with ``--force``.
    ``--force`` is used only when the caller explicitly sets ``force=True``,
    meaning the worktree is intentionally dirty and safe to drop.
    """

    project = Path(project)
    worktree_path = Path(worktree_path)
    with _creation_lock(project):
        if not worktree_path.exists():
            run_git(
                ["git", "-C", str(project), "worktree", "prune"],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            return False
        if _run_worktree_remove(project, worktree_path, force=force):
            return True
    raise WorktreeSessionError(
        f"cannot remove isolated worker worktree at {worktree_path}: git worktree remove failed"
    )


def _run_worktree_remove(project: Path, worktree_path: Path, *, force: bool) -> bool:
    args = ["git", "-C", str(project), "worktree", "remove"]
    if force:
        args.append("--force")
    args.append(str(worktree_path))
    completed = subprocess.run(
        args,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return completed.returncode == 0
