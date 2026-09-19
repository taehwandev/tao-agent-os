"""Conservative content binding for a separate shared review-rules checkout."""

from __future__ import annotations

import hashlib
import stat
from pathlib import Path

from agent_worktree_fingerprint import git_output, worktree_signature


# These own shell admission, not review/finish acceptance. Unknown production
# files remain included. Do not grow this set from an agent's prose claim.
_ADMISSION_ONLY = frozenset({
    "scripts/claude_bash_http.py", "scripts/claude_bash_readonly.py",
    "scripts/claude_bash_git.py", "scripts/claude_bash_paths.py",
    "scripts/claude_bash_syntax.py",
})


def review_rules_inputs(project: Path, rules: Path) -> str | None:
    """Hash all rules inputs except known independent tests/admission modules.

No exemption applies when rules are the reviewed repository. Older receipts
and non-Git roots retain their exact-state check. Failure to inspect is not
permission to reuse. Paths, modes, additions, deletions and content all bind.
"""
    try:
        project_root = git_output(project, "rev-parse", "--show-toplevel").strip()
        rules_root = git_output(rules, "rev-parse", "--show-toplevel").strip()
        if Path(project_root).resolve() == Path(rules_root).resolve():
            return None
        if Path(rules_root).resolve() != rules.resolve():
            return None  # Subdirectory rule roots retain the conservative path.
        before = git_output(rules, "rev-parse", "HEAD").strip()
        signature = worktree_signature(rules)
        paths = sorted(set(git_output(
            rules, "ls-files", "-z", "--cached", "--others", "--exclude-standard"
        ).split("\0")) - {""})
        digest = hashlib.sha256(b"review-rules-inputs-v1\0")
        budget = 64 * 1024 * 1024
        for name in paths:
            if name.startswith("tests/") or name in _ADMISSION_ONLY:
                continue
            path = rules / name
            digest.update(name.encode("utf-8") + b"\0")
            if not path.exists() and not path.is_symlink():
                digest.update(b"deleted\0")
                continue
            info = path.lstat()
            if not stat.S_ISREG(info.st_mode) or path.resolve().parent != path.parent.resolve():
                return None
            path.resolve().relative_to(rules.resolve())
            budget -= info.st_size
            if budget < 0:
                return None
            content = path.read_bytes()
            if path.stat() != info:
                return None
            digest.update(str(stat.S_IMODE(info.st_mode)).encode() + b"\0")
            digest.update(hashlib.sha256(content).digest())
        if (git_output(rules, "rev-parse", "HEAD").strip() != before
                or worktree_signature(rules) != signature):
            return None
        return digest.hexdigest()
    except (OSError, RuntimeError, ValueError):
        return None
