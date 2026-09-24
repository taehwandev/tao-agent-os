"""Throwaway checkouts under the OS temp directory, whose files are scratch.

A measurement worktree parked in the session scratchpad was governed like the
project it came from: deleting a probe file in it, and removing the worktree
from its parent, each asked for a full workflow lifecycle in a checkout that
existed only to be thrown away. Its files land in no project anyone keeps.
Publishing from it, and writing the repository refs it shares, still reach the
real project, so only file writes and the worktree's own removal are released.

Owner: whether a governed root is a throwaway checkout -- it resolves strictly
inside the OS temp directory while its repository is anchored outside it --
and whether a command line only writes files there or removes that worktree.
Allowed imports: the standard library, claude_bash_syntax, claude_bash_git,
claude_bash_raw_lines and claude_pretool_publication.
Forbidden imports: claude_pretool_gate and run evidence; this is decided from
the filesystem and the command text alone.
Callers/tests: claude_pretool_gate._call_scope;
tests/test_claude_temp_checkout_scratch.py.
Verification: that module and the full gate suite.
"""

from __future__ import annotations

import re
from pathlib import Path

import claude_bash_syntax as syntax
from claude_bash_git import git_subcommand
from claude_bash_raw_lines import raw_command_segments
from claude_bash_syntax import (
    SHELL_PROGRAMS,
    SHELL_STRUCTURE_WORDS,
    command_behind_wrappers,
    computed_word,
)
from claude_pretool_publication import publication_hold

# Git subcommands that only drop a throwaway worktree's administrative entry.
WORKTREE_DISPOSAL = frozenset({"remove", "prune"})
# Programs that write shared repository state or publish when named anywhere.
REPOSITORY_PROGRAMS = frozenset({"git", "gh"})
_REMOTE_URL_RE = re.compile(r"^\s*url\s*=\s*(\S.*?)\s*$")
_SCP_LIKE_RE = re.compile(r"^[^/:]+:")


def _inside_temp(path: Path) -> bool:
    return any(
        path != root and path.is_relative_to(root) for root in syntax.scratch_roots()
    )


def throwaway_checkout(root: Path) -> bool:
    """Whether this project root is a disposable checkout of a project kept elsewhere.

    The root is resolved first, so a temp-looking spelling that links into a
    real project is judged where it lands. A repository created in temp with no
    anchor outside it -- a test fixture, say -- stays a project.
    """

    try:
        resolved = root.resolve()
        return _inside_temp(resolved) and _anchored_outside_temp(resolved)
    except (OSError, ValueError):
        return False


def _anchored_outside_temp(root: Path) -> bool:
    marker = root / ".git"
    if marker.is_file():
        return _linked_common_dir_outside_temp(root, marker)
    if marker.is_dir():
        return any(
            not _inside_temp(location)
            for location in _remote_locations(root, marker / "config")
        )
    return False


def _linked_common_dir_outside_temp(root: Path, marker: Path) -> bool:
    text = marker.read_text(encoding="utf-8", errors="ignore").strip()
    if not text.startswith("gitdir:"):
        return False
    gitdir = Path(text.split(":", 1)[1].strip())
    gitdir = gitdir if gitdir.is_absolute() else root / gitdir
    if not gitdir.is_dir():
        # A link to metadata that is not there anchors nothing.
        return False
    common = gitdir
    pointer = gitdir / "commondir"
    if pointer.is_file():
        named = Path(pointer.read_text(encoding="utf-8", errors="ignore").strip())
        common = named if named.is_absolute() else gitdir / named
    common = common.resolve()
    return common.is_dir() and not _inside_temp(common)


def _remote_locations(root: Path, config: Path) -> list[Path]:
    """Where each remote lives; a network remote reads as outside temp."""

    try:
        lines = config.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    locations: list[Path] = []
    for line in lines:
        match = _REMOTE_URL_RE.match(line)
        if not match:
            continue
        url = match.group(1).strip('"')
        if url.startswith("file://"):
            url = url[len("file://"):]
        elif "://" in url or _SCP_LIKE_RE.match(url):
            locations.append(Path("/"))
            continue
        location = Path(url).expanduser()
        location = (location if location.is_absolute() else root / location).resolve()
        if location.exists():
            locations.append(location)
    return locations


def writes_only_scratch_files(command: str, root: Path, cwd: Path) -> bool:
    """Whether every segment only touches files, or disposes of a worktree.

    Anything that could reach the repository the checkout shares -- a Git
    command other than `worktree remove|prune`, `gh`, a publication, a shell
    or wrapper whose program cannot be read -- keeps the checkout governed.
    """

    if publication_hold(command, root=root, cwd=cwd):
        return False
    segments = raw_command_segments(command)
    if segments is None:
        return False
    return all(_segment_only_touches_files(tokens) for tokens in segments)


def _segment_only_touches_files(tokens: list[str]) -> bool:
    program = command_behind_wrappers(tokens)
    if program is None:
        return False
    if not program:
        return True
    head = Path(program[0]).name
    if (
        head in SHELL_PROGRAMS
        or head in SHELL_STRUCTURE_WORDS
        or head == "eval"
        or any(computed_word(token) for token in program)
    ):
        return False
    if any(Path(token).name in REPOSITORY_PROGRAMS for token in program[1:]):
        return False
    if head == "gh":
        return False
    if head != "git":
        return True
    subcommand, arguments = git_subcommand(program)
    return (
        subcommand == "worktree"
        and bool(arguments)
        and arguments[0] in WORKTREE_DISPOSAL
    )
