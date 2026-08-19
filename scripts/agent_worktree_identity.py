"""Identity and generated-path policy for isolated Git worker worktrees."""

from __future__ import annotations

import subprocess
import uuid
from pathlib import Path
from re import fullmatch
from support.bounded_git import run_git


WORKTREE_DIRNAME = "worktrees"
_GENERATED_WORKTREE_NAME = r"[0-9a-f]{16}"


class WorktreeSessionError(RuntimeError):
    """Raised when an isolated worker worktree fails lifecycle validation."""


def worktree_root(project: Path) -> Path:
    """Return the parent directory that holds per-worker worktrees."""

    return Path(project) / ".tao" / WORKTREE_DIRNAME


def new_worktree_path(project: Path) -> Path:
    """Return a fresh, unused worktree path under the project worktree root."""

    return worktree_root(project) / uuid.uuid4().hex[:16]


def generated_worker_path(project: Path, worktree_path: Path) -> Path:
    """Return a canonical generated-worker target or reject it before mutation."""

    project = Path(project).expanduser().resolve()
    candidate = Path(worktree_path).expanduser()
    if not candidate.is_absolute():
        raise WorktreeSessionError(
            "worker worktree must use an absolute generated worker path"
        )
    expected_root = worktree_root(project)
    canonical_root = expected_root.resolve(strict=False)
    canonical_candidate = candidate.resolve(strict=False)
    if canonical_candidate.parent != canonical_root or fullmatch(
        _GENERATED_WORKTREE_NAME, canonical_candidate.name
    ) is None:
        raise WorktreeSessionError(
            "worker worktree must be a direct generated worker path under "
            f"{expected_root}"
        )
    for component in (project / ".tao", expected_root):
        if component.is_symlink():
            raise WorktreeSessionError(
                "generated worker path must not resolve through a symlink"
            )
    if candidate.exists() and candidate.is_symlink():
        raise WorktreeSessionError(
            "generated worker path must not resolve through a symlink"
        )
    return canonical_candidate


def _git_text(path: Path, *args: str) -> str:
    completed = run_git(
        ["git", "-C", str(path), *args],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise WorktreeSessionError(
            f"cannot verify isolated worker worktree: git {args[0]} failed"
        )
    return completed.stdout.decode("utf-8", "replace").strip()


def _git_common_dir(path: Path) -> Path:
    common_dir = Path(_git_text(path, "rev-parse", "--git-common-dir"))
    if not common_dir.is_absolute():
        common_dir = path / common_dir
    return common_dir.resolve()


def validate_worker_worktree_identity(project: Path, worktree_path: Path) -> Path:
    """Prove that a generated path is a linked worktree of ``project``.

    A path merely containing a Git repository is insufficient. The candidate
    must be the generated direct child, be the repository top level, use a
    linked-worktree ``.git`` file, and share Git's common directory with the
    parent project. Any mismatch fails before Codex can receive project trust.
    """

    project = Path(project).expanduser().resolve()
    candidate = generated_worker_path(project, worktree_path)
    git_link = candidate / ".git"
    if not candidate.is_dir() or not git_link.exists() or git_link.is_symlink():
        raise WorktreeSessionError(
            "generated worker path is not a registered linked git worktree"
        )
    if _git_text(candidate, "rev-parse", "--is-inside-work-tree") != "true":
        raise WorktreeSessionError(
            "generated worker path is not inside a git worktree"
        )
    top_level = Path(_git_text(candidate, "rev-parse", "--show-toplevel")).resolve()
    if top_level != candidate:
        raise WorktreeSessionError(
            "generated worker path is not the git worktree top level"
        )
    if _git_common_dir(project) != _git_common_dir(candidate):
        raise WorktreeSessionError(
            "generated worker path does not belong to the same git repository"
        )
    if not git_link.is_file():
        raise WorktreeSessionError(
            "generated worker path is not a registered linked git worktree"
        )
    return candidate


def resolve_base_ref(project: Path) -> str:
    """Return the current HEAD commit the worker worktree should branch from."""

    completed = run_git(
        ["git", "-C", str(project), "rev-parse", "HEAD"],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        raise WorktreeSessionError(
            "cannot resolve base ref for worker worktree: git rev-parse HEAD failed"
        )
    head = completed.stdout.decode("utf-8").strip()
    if not head:
        raise WorktreeSessionError("git rev-parse HEAD returned an empty base ref")
    return head
