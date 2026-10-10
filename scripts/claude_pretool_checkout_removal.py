"""Refuse a command that deletes a checkout still holding work or an open run.

Owner: which checkouts a shell command removes outright -- `git worktree
remove` (forced or not) and a recursive `rm` of a checkout or of the folder
holding checkouts -- and the refusal when one of them still holds work.
Allowed imports: the standard library, claude_bash_git, claude_scratch_checkout
and agent_repository_checkouts.
Forbidden imports: claude_pretool_gate and any run-evidence or policy reader.
Callers/tests: claude_pretool_gate._decide; tests/test_claude_pretool_checkout_removal.py.
Verification: that test module and tests/test_safe_ref_cleanup.py.

A task worktree was deleted while a worker ran its tests in it: modified
files, an untracked test and a running Tao run went with it. Its branch had
no commits of its own, so it sat at an ancestor of main and every "merged"
check said it could go. `git worktree remove` refuses a dirty checkout, but
`--force` and `rm -rf` do not, and a Tao run lives in an ignored directory
that git never counts. The gate answered a forced removal by deferring to the
runtime's own permission flow, which cannot see either. This module looks.
"""

from __future__ import annotations

from pathlib import Path

from agent_repository_checkouts import checkout_removal_hazard
from claude_bash_git import git_subcommand
from claude_scratch_checkout import throwaway_checkout

_SEPARATORS = frozenset({";", "&", "&&", "|", "||"})
# A folder holding checkouts is scanned one level deep, bounded so that an
# `rm -rf` of a large tree costs a directory listing, not a walk.
_MAX_CHILDREN = 256


def checkout_removal_denial(tokens: list[str], cwd: Path) -> str:
    """The refusal for this command, or "" when it removes no checkout at risk."""

    here = cwd
    for segment in _segments(tokens):
        if segment[0] == "cd" and len(segment) == 2:
            here = _absolute(segment[1], here)
            continue
        for target in _removed_paths(segment, here):
            for checkout in _checkouts_at(target):
                # A temp checkout of a project kept elsewhere is disposable by
                # design, so its files are scratch; an open run in it is not.
                hazard = checkout_removal_hazard(
                    checkout, count_changes=not throwaway_checkout(checkout)
                )
                if hazard:
                    return (
                        f"This command deletes the checkout {checkout}, but {hazard}. "
                        "Deleting it loses that work, and a merged-looking branch does "
                        "not mean the checkout is finished: commit or discard the changes "
                        "and finish or cancel the run there first, or leave it in place."
                    )
    return ""


def _segments(tokens: list[str]) -> list[list[str]]:
    segments: list[list[str]] = [[]]
    for token in tokens:
        if token in _SEPARATORS:
            segments.append([])
        else:
            segments[-1].append(token)
    return [segment for segment in segments if segment]


def _removed_paths(segment: list[str], cwd: Path) -> list[Path]:
    name = Path(segment[0]).name
    if name == "rm":
        arguments = segment[1:]
        options = [a for a in arguments if a.startswith("-") and a != "-"]
        recursive = "--recursive" in options or any(
            not option.startswith("--") and set(option[1:]) & {"r", "R"} for option in options
        )
        if not recursive:
            return []
        operands = _operands(arguments)
        return [_absolute(operand, cwd) for operand in operands]
    if name != "git":
        return []
    subcommand, arguments = git_subcommand(segment)
    if subcommand != "worktree" or not arguments or arguments[0] != "remove":
        return []
    return [_absolute(operand, _git_cwd(segment, arguments, cwd)) for operand in _operands(arguments[1:])]


def _operands(arguments: list[str]) -> list[str]:
    if "--" in arguments:
        split = arguments.index("--")
        return [a for a in arguments[:split] if not a.startswith("-")] + arguments[split + 1:]
    return [a for a in arguments if not a.startswith("-")]


def _git_cwd(segment: list[str], arguments: list[str], cwd: Path) -> Path:
    """Apply Git's global `-C` options, each relative to the one before."""

    here = cwd
    globals_end = len(segment) - len(arguments) - 1
    index = 1
    while index < globals_end:
        token = segment[index]
        if token == "-C" and index + 1 < globals_end:
            here = _absolute(segment[index + 1], here)
            index += 2
            continue
        if token.startswith("-C="):
            here = _absolute(token.split("=", 1)[1], here)
        index += 1
    return here


def _absolute(raw: str, cwd: Path) -> Path:
    # The parent is resolved and the last component kept, so `rm -rf link`
    # is read as removing the link, which is all it removes.
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = cwd / path
    if path.name in {"", ".", ".."}:
        try:
            return path.resolve()
        except OSError:
            return path
    try:
        return path.parent.resolve() / path.name
    except OSError:
        return path


def _checkouts_at(target: Path) -> list[Path]:
    """``target`` if it is a checkout, else the checkouts directly inside it."""

    if not _is_real_directory(target):
        return []
    if _has_git_marker(target):
        return [target]
    try:
        children = sorted(target.iterdir())[:_MAX_CHILDREN]
    except OSError:
        return []
    return [child for child in children if _is_real_directory(child) and _has_git_marker(child)]


def _is_real_directory(path: Path) -> bool:
    try:
        return path.is_dir() and not path.is_symlink()
    except OSError:
        return False


def _has_git_marker(path: Path) -> bool:
    try:
        return (path / ".git").exists()
    except OSError:
        return False
