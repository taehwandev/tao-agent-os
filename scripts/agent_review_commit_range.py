"""Immutable committed-subject preparation for the review hook."""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any


CommandRunner = Callable[[list[str], Path], dict[str, Any]]


def resolve_commit_range_subject(
    project: Path,
    base_ref: str,
    head_ref: str,
    run_command: CommandRunner,
) -> dict[str, Any]:
    """Resolve one ordered, non-empty commit range to immutable Git objects."""

    resolved: dict[str, str] = {}
    for label, ref in (("base", base_ref.strip()), ("head", head_ref.strip())):
        if not ref or ref.startswith("-"):
            raise ValueError(f"commit-range {label} ref is missing or unsafe")
        result = run_command(
            ["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
            project,
        )
        sha = str(result.get("stdout") or "").strip()
        if result.get("returncode") != 0 or not _is_git_sha(sha):
            raise ValueError(f"commit-range {label} ref does not resolve to a commit")
        resolved[label] = sha

    ancestor = run_command(
        ["git", "merge-base", "--is-ancestor", resolved["base"], resolved["head"]],
        project,
    )
    if ancestor.get("returncode") != 0:
        raise ValueError("commit-range base must be an ancestor of head")

    discovery = run_command(
        [
            "git",
            "diff",
            "--name-only",
            "-z",
            "--diff-filter=ACDMRTUXB",
            resolved["base"],
            resolved["head"],
            "--",
        ],
        project,
    )
    if discovery.get("returncode") != 0:
        raise ValueError("commit-range changed path discovery failed")
    changed_paths = _nul_paths(str(discovery.get("stdout") or ""))
    if not changed_paths:
        raise ValueError("commit-range has no changed paths")
    return {
        "kind": "commit-range",
        "base_sha": resolved["base"],
        "head_sha": resolved["head"],
        "changed_paths": changed_paths,
        "path_discovery": discovery,
    }


def create_commit_snapshot(
    project: Path,
    head_sha: str,
    run_command: CommandRunner,
) -> tuple[tempfile.TemporaryDirectory[str], Path, dict[str, Any]]:
    """Materialize the exact reviewed tree in an isolated local clone."""

    temporary = tempfile.TemporaryDirectory(prefix="tao-agent-review-")
    source_root = Path(temporary.name) / "tree"
    clone = run_command(
        [
            "git",
            "clone",
            "--quiet",
            "--no-checkout",
            "--shared",
            "--",
            str(project.resolve()),
            str(source_root),
        ],
        project,
    )
    if clone.get("returncode") != 0:
        temporary.cleanup()
        raise RuntimeError("local Git clone could not materialize the reviewed repository")
    checkout = run_command(
        ["git", "-C", str(source_root), "checkout", "--quiet", "--detach", head_sha],
        project,
    )
    verified = run_command(
        ["git", "-C", str(source_root), "rev-parse", "--verify", "HEAD^{commit}"],
        project,
    )
    if (
        checkout.get("returncode") != 0
        or verified.get("returncode") != 0
        or str(verified.get("stdout") or "").strip() != head_sha
    ):
        temporary.cleanup()
        raise RuntimeError("local Git clone could not check out the reviewed head commit")
    return temporary, source_root, {
        "commands": [clone.get("command"), checkout.get("command"), verified.get("command")],
        "returncode": 0,
        "head_sha": head_sha,
        "source": "isolated local Git clone",
    }


def _is_git_sha(value: str) -> bool:
    return len(value) in {40, 64} and all(
        character in "0123456789abcdef" for character in value
    )


def _nul_paths(output: str) -> list[str]:
    if "\0" in output:
        return [path for path in output.split("\0") if path]
    return [line.strip() for line in output.splitlines() if line.strip()]
