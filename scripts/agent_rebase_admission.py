"""Bound a post-finish rebase to one clean task worktree and one upstream.

Owner: local rebase shape and target checks. Allowed: pathlib and subprocess.
Forbidden: Git mutations or authority inference. Caller: claude_pretool_gate;
verification: tests.test_agent_rebase_admission.
"""

from __future__ import annotations

from pathlib import Path
import subprocess


def rebase_continuation_shape(root: Path, arguments: list[str], protected: set[str]) -> bool:
    """The caller checks the current finish receipt and git_write authority.

    Disable configuration that can modify other branches or stash user work.
    Rebase may change inputs; subsequent publication still checks the original
    receipt against the resulting bytes. This grants no renewed finish.
    """
    flags = {"--no-update-refs", "--no-autostash", "--no-autosquash"}
    if len(arguments) != 4 or set(arguments[:3]) != flags:
        return False
    upstream = arguments[-1]
    if not upstream or upstream.startswith("-") or not (root / ".git").is_file():
        return False

    def read(*args: str) -> str | None:
        try:
            result = subprocess.run(["git", "-C", str(root), *args],
                                    capture_output=True, text=True, timeout=5)
            return result.stdout.strip() if result.returncode == 0 else None
        except (OSError, subprocess.SubprocessError):
            return None

    branch = read("symbolic-ref", "--quiet", "--short", "HEAD")
    if not branch or branch in protected or read("status", "--porcelain", "--untracked-files=all") != "":
        return False
    for state in ("rebase-merge", "rebase-apply", "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD"):
        path = read("rev-parse", "--git-path", state)
        if path is None or (root / path).exists():
            return False
    commit = read("rev-parse", "--verify", "--end-of-options", upstream + "^{commit}")
    return bool(commit and read("merge-base", "HEAD", commit))
