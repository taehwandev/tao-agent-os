"""Throwaway checkouts under the OS temp directory, whose files are scratch.

A measurement worktree parked in the session scratchpad was governed like the
project it came from: deleting a probe file in it, and removing the worktree
from its parent, each asked for a full workflow lifecycle in a checkout that
existed only to be thrown away. Its files land in no project anyone keeps.
Publishing from it, and writing the repository refs it shares, still reach the
real project, so only file writes and the worktree's own removal are released.
A file write is released only when it is proven to land in temp: a program
that runs code -- `python3 script.py`, `npm run`, `make`, `./tool` -- can write
into the real project (through TAO_HOME, say), so it stays governed.

Owner: whether a governed root is a throwaway checkout -- it resolves strictly
inside the OS temp directory while its repository is anchored outside it --
and whether a command line only writes files inside temp or removes that
worktree.
Allowed imports: the standard library, claude_bash_syntax, claude_bash_git,
claude_bash_raw_lines, claude_bash_readonly and claude_pretool_publication.
Forbidden imports: claude_pretool_gate and run evidence; this is decided from
the filesystem and the command text alone.
Callers/tests: claude_pretool_gate._call_scope;
tests/test_claude_temp_checkout_scratch.py.
Verification: that module and the full gate suite.
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

import claude_bash_syntax as syntax
from claude_bash_git import git_subcommand
from claude_bash_raw_lines import raw_command_segments
from claude_bash_readonly import simple_command_kind
from claude_bash_syntax import (
    DIRECTORY_CHANGERS,
    ENV_ASSIGNMENT_PREFIX_RE,
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
# File utilities that write only the paths they are given. Each is released
# only when every one of those paths resolves inside temp; any other program
# may write anywhere and keeps the checkout governed.
TEMP_FILE_UTILITIES = frozenset(
    {"rm", "rmdir", "mv", "cp", "mkdir", "touch", "ln", "chmod"}
)
_SEPARATORS = frozenset({";", "&", "&&", "|", "||"})
_OUTPUT_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>"})
_INPUT_REDIRECTS = frozenset({"<", "<<<"})
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
    """Whether every write on the line provably lands in temp.

    Only a listed file utility whose every path operand resolves inside an OS
    temp directory, a command the read-only classifier already calls a read,
    a redirect into temp, and `git worktree remove|prune` qualify. Any other
    program -- an interpreter, a package manager, a build tool, a `./tool`,
    anything behind an assignment or a wrapper -- can write wherever it likes,
    so it keeps the checkout governed, as does whatever could reach the
    repository the checkout shares.
    """

    if publication_hold(command, root=root, cwd=cwd):
        return False
    if raw_command_segments(command) is None:
        return False
    segments = _segments_with_redirects_in_temp(command, cwd)
    if segments is None:
        return False
    for words in segments:
        if words and words[0] in DIRECTORY_CHANGERS:
            cwd = _changed_directory(words)
            if cwd is None:
                return False
            continue
        if not _segment_only_touches_temp(words, cwd):
            return False
    return True


def _segments_with_redirects_in_temp(command: str, cwd: Path) -> "list[list[str]] | None":
    """The words of each simple command, once every redirect is proven harmless.

    An output redirect must land in temp or the discard sink; an input redirect
    only reads. Any operator not modelled here leaves the line unread.
    """

    lines = syntax._shell_lines(command)
    if lines is None:
        return None
    try:
        lexer = shlex.shlex(lines, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return None
    segments: list[list[str]] = [[]]
    index = 0
    while index < len(tokens):
        token = tokens[index]
        following = tokens[index + 1] if index + 1 < len(tokens) else ""
        if token in _SEPARATORS:
            segments.append([])
            index += 1
            continue
        if token in _OUTPUT_REDIRECTS:
            if following not in syntax.DISCARD_TARGETS and not _path_in_temp(following, cwd):
                return None
            index += 2
            continue
        if token in _INPUT_REDIRECTS:
            if not following:
                return None
            index += 2
            continue
        if token in syntax.FD_DUPLICATIONS:
            if not syntax.FD_OPERAND_RE.fullmatch(following):
                return None
            index += 2
            continue
        if set(token) <= syntax.OPERATOR_CHARS:
            return None
        segments[-1].append(token)
        index += 1
    return [segment for segment in segments if segment]


def _changed_directory(words: list[str]) -> "Path | None":
    """Where a `cd` moves the rest of the line, when it names an absolute place."""

    if words[0] != "cd" or len(words) != 2 or not Path(words[1]).is_absolute():
        return None
    if set(words[1]) & syntax.UNRESOLVED_PATH_CHARS:
        return None
    return Path(words[1])


def _segment_only_touches_temp(words: list[str], cwd: Path) -> bool:
    program = command_behind_wrappers(words)
    if program and Path(program[0]).name == "git":
        return _disposes_of_worktree(program)
    head = words[0]
    if (
        head != Path(head).name
        or ENV_ASSIGNMENT_PREFIX_RE.match(head)
        or head in SHELL_PROGRAMS
        or head in SHELL_STRUCTURE_WORDS
        or head == "eval"
        or any(computed_word(word) for word in words)
        or any(Path(word).name in REPOSITORY_PROGRAMS for word in words)
    ):
        return False
    if head in TEMP_FILE_UTILITIES:
        return _operands_in_temp(head, words[1:], cwd)
    return simple_command_kind(words, cwd) == "read_only"


def _disposes_of_worktree(program: list[str]) -> bool:
    if any(computed_word(token) for token in program):
        return False
    if any(Path(token).name in REPOSITORY_PROGRAMS for token in program[1:]):
        return False
    subcommand, arguments = git_subcommand(program)
    return (
        subcommand == "worktree"
        and bool(arguments)
        and arguments[0] in WORKTREE_DISPOSAL
    )


def _operands_in_temp(utility: str, arguments: list[str], cwd: Path) -> bool:
    """Whether every path a listed file utility names resolves inside temp.

    Options are stepped over; one carrying `=` may hide a path (as in
    `--target-directory=`), so it is refused. A value an option takes is read
    as an operand, which can only refuse more. `chmod`'s mode is not a path.
    """

    operands: list[str] = []
    options_done = False
    for argument in arguments:
        if not options_done and argument == "--":
            options_done = True
            continue
        if not options_done and argument.startswith("-") and argument != "-":
            if "=" in argument:
                return False
            continue
        operands.append(argument)
    if utility == "chmod":
        if not operands:
            return True
        operands = operands[1:]
    if not all(_path_in_temp(operand, cwd) for operand in operands):
        return False
    if utility == "ln":
        # A relative link target is read from the link's own directory.
        places = [cwd, *(_absolute(operand, cwd).parent for operand in operands)]
        return all(
            _path_in_temp(operand, place)
            for operand in operands
            for place in places
        )
    return True


def _absolute(raw: str, cwd: Path) -> Path:
    path = Path(raw)
    return path if path.is_absolute() else cwd / path


def _path_in_temp(raw: str, cwd: Path) -> bool:
    """Whether `raw` resolves, `..` and symlinks followed, strictly inside temp."""

    if not raw or set(raw) & syntax.UNRESOLVED_PATH_CHARS:
        return False
    try:
        return _inside_temp(_absolute(raw, cwd).resolve(strict=False))
    except (OSError, RuntimeError, ValueError):
        return False
