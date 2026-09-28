"""Recognize creation of one empty project directory at any safe location.

Owner: initial directory admission. Allowed imports: pathlib only.
Forbidden: writes, execution, runtime state. Caller: shell classifier.
Verification: test_claude_project_bootstrap; native filesystem permissions apply.
"""
from __future__ import annotations

from pathlib import Path


def project_directory_bootstrap(tokens: list[str]) -> bool:
    """Allow one new literal directory outside an existing Git project."""
    if not tokens or tokens[0] != "mkdir":
        return False
    arguments = tokens[1:]
    recursive = arguments[:1] == ["-p"]
    if recursive:
        arguments = arguments[1:]
    if len(arguments) != 1 or arguments[0].startswith("-"):
        return False
    target = Path(arguments[0])
    if not target.is_absolute() or target.name.startswith(".") or ".." in target.parts:
        return False
    try:
        if target.exists() or target.is_symlink():
            return False
        parent = target.parent
        if not recursive and not parent.is_dir():
            return False
        while not parent.exists() and not parent.is_symlink():
            parent = parent.parent
        parent = parent.resolve(strict=True)
        if not parent.is_dir() or any(
            (ancestor / ".git").exists() for ancestor in (parent, *parent.parents)
        ):
            return False
    except (OSError, ValueError, RuntimeError):
        return False
    return True
