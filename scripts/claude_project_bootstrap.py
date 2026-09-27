"""Recognize creation of one empty project directory in a routing workspace.

Owner: initial directory admission. Allowed imports: pathlib only.
Forbidden: writes, execution, runtime state. Caller: shell classifier.
Verification: test_claude_project_bootstrap; native filesystem permissions apply.
"""
from __future__ import annotations

from pathlib import Path


def project_directory_bootstrap(tokens: list[str]) -> bool:
    """Require a declared non-Git workspace and a new literal direct child."""
    if not tokens or tokens[0] != "mkdir":
        return False
    arguments = tokens[1:]
    if arguments[:1] == ["-p"]:
        arguments = arguments[1:]
    if len(arguments) != 1 or arguments[0].startswith("-"):
        return False
    target = Path(arguments[0])
    if not target.is_absolute() or target.name.startswith("."):
        return False
    try:
        parent = target.parent.resolve(strict=True)
        if parent != target.parent or target.exists() or target.is_symlink():
            return False
        if any((ancestor / ".git").exists() for ancestor in (parent, *parent.parents)):
            return False
        guidance = (parent / "AGENTS.md").read_text(encoding="utf-8")
    except (OSError, ValueError, RuntimeError):
        return False
    return "<!-- BEGIN MANAGED TAO AGENT OS WORKSPACE GUARD -->" in guidance
