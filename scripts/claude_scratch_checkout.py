"""Throwaway checkouts under the OS temp directory, whose files are scratch.

A measurement worktree parked in the session scratchpad was governed like the
project it came from: deleting a probe file in it, and removing the worktree
from its parent, each asked for a full workflow lifecycle in a checkout that
existed only to be thrown away. Its files land in no project anyone keeps.
Publishing from it, and writing the repository refs it shares, still reach the
real project, so those keep the checkout governed.

Code run there -- `python3 script.py`, `npm test`, `make`, `./tool` -- is
released too: that it *could* write anywhere is no risk the command shows. What
the command shows is judged instead. A word, an option value, an assignment's
value or a redirect target that resolves into a governed project outside temp,
or into the repository the checkout shares, keeps the checkout governed, so
`TAO_HOME=<project> python3 x.py` gets the verdict it had before the exemption.
Known file utilities are held to more: their write operands and redirect
targets must resolve inside temp, with only options whose effect is known.
Keeping the checkout governed is the only effect: nothing here denies anything.

Owner: whether a governed root is a throwaway checkout -- it resolves strictly
inside the OS temp directory while its repository is anchored outside it --
and whether a command line run there visibly reaches a real project or the
shared repository.
Allowed imports: the standard library, claude_bash_syntax, claude_bash_git,
claude_bash_raw_lines, claude_bash_readonly and claude_pretool_publication.
Forbidden imports: claude_pretool_gate and run evidence; this is decided from
the filesystem and the command text alone, and the gate hands in how it finds
the project owning a path.
Callers/tests: claude_pretool_gate._call_scope;
tests/test_claude_temp_checkout_scratch.py.
Verification: that module and the full gate suite.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path
from typing import Callable, Iterator

import claude_bash_syntax as syntax
from claude_bash_git import git_subcommand
from claude_bash_raw_lines import raw_command_segments
from claude_bash_readonly import simple_command_kind
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
# File utilities whose writes are read from their operands, with the short
# options whose effect is known; any other option leaves the line governed.
FILE_UTILITIES = {
    "rm": frozenset("rfivR"),
    "rmdir": frozenset("v"),
    "mv": frozenset("finv"),
    "cp": frozenset("rRafnpv"),
    "mkdir": frozenset("pv"),
    "touch": frozenset("acmv"),
    "ln": frozenset("sfnv"),
    "chmod": frozenset("Rfv"),
}
_SEPARATORS = frozenset({";", "&", "&&", "|", "||"})
_OUTPUT_REDIRECTS = frozenset({">", ">>", ">|", "&>", "&>>"})
_INPUT_REDIRECTS = frozenset({"<", "<<<"})
_REMOTE_URL_RE = re.compile(r"^\s*url\s*=\s*(\S.*?)\s*$")
_SCP_LIKE_RE = re.compile(r"^[^/:]+:")
# The home directory spelled the ways the shell expands before running.
_HOME_PREFIX_RE = re.compile(r"^(?:~|\$\{HOME\}|\$HOME)(?=/|$)")
_HOME_VARIABLE_RE = re.compile(r"(?:\$\{HOME\}|\$HOME)(?=/|:|$)")
# An absolute or home-rooted path inside a longer word, as in inline code.
_EMBEDDED_PATH_RE = re.compile(r"(?:~|\$\{HOME\}|\$HOME)?/[^\s'\"`:;,()<>|&=$]*")
# One unnested brace alternation, which the shell expands into several words.
_BRACE_RE = re.compile(r"^(.*?)\{([^{}]*,[^{}]*)\}(.*)$")

ProjectOf = Callable[[Path], "Path | None"]


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
        return _linked_common_dir(root, marker) is not None
    if marker.is_dir():
        return any(
            not _inside_temp(location)
            for location in _remote_locations(root, marker / "config")
        )
    return False


def _linked_common_dir(root: Path, marker: Path) -> "Path | None":
    """The repository directory a linked worktree shares, when outside temp."""

    text = marker.read_text(encoding="utf-8", errors="ignore").strip()
    if not text.startswith("gitdir:"):
        return None
    gitdir = Path(text.split(":", 1)[1].strip())
    gitdir = gitdir if gitdir.is_absolute() else root / gitdir
    if not gitdir.is_dir():
        # A link to metadata that is not there anchors nothing.
        return None
    common = gitdir
    pointer = gitdir / "commondir"
    if pointer.is_file():
        named = Path(pointer.read_text(encoding="utf-8", errors="ignore").strip())
        common = named if named.is_absolute() else gitdir / named
    common = common.resolve()
    return common if common.is_dir() and not _inside_temp(common) else None


def _shared_repository(root: Path) -> "Path | None":
    try:
        resolved = root.resolve()
        marker = resolved / ".git"
        return _linked_common_dir(resolved, marker) if marker.is_file() else None
    except (OSError, ValueError):
        return None


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


def scratch_command(command: str, root: Path, cwd: Path, project_of: ProjectOf) -> bool:
    """Whether the line leaves real projects alone, so the checkout is scratch.

    Any program may run -- an interpreter, a package manager, a build tool, a
    `./tool`, an assignment-prefixed or wrapped program. The line is not
    scratch only when it visibly reaches out: a word, option value,
    assignment value, `cd` target or redirect target resolving (`..` and
    symlinks followed, relative to the effective cwd, `~` and `$HOME`
    expanded) into a project `project_of` names outside temp or into the
    shared repository; a file utility writing outside temp or with an option
    not modelled; a Git command other than a read or `worktree remove|prune`;
    `gh`; a publication; or a line that cannot be read.
    """

    if publication_hold(command, root=root, cwd=cwd):
        return False
    if raw_command_segments(command) is None:
        return False
    reach = _Reach(project_of, _shared_repository(root))
    segments = _segments(command, cwd, reach)
    if segments is None:
        return False
    for words in segments:
        if words[0] in syntax.DIRECTORY_CHANGERS:
            cwd = _changed_directory(words, cwd)
            if (cwd is None or not cwd.is_dir()
                    or not syntax.scratch_write_target(str(cwd), cwd)
                    or reach.touches(str(cwd), cwd)):
                return False
            continue
        if not _segment_is_scratch(words, cwd, reach):
            return False
    return True


class _Reach:
    """Whether a spelled path lands in a real project or the shared repository."""

    def __init__(self, project_of: ProjectOf, shared: "Path | None") -> None:
        self._project_of = project_of
        self._shared = shared

    def touches(self, raw: str, cwd: Path) -> bool:
        spelled = _expand_home(raw)
        if spelled is None:
            return False
        path = Path(spelled)
        if not path.is_absolute():
            path = cwd / path
        try:
            resolved = path.resolve(strict=False)
        except (OSError, RuntimeError, ValueError):
            return False
        if _inside_temp(resolved):
            return False
        if self._shared is not None and resolved.is_relative_to(self._shared):
            return True
        try:
            owner = self._project_of(resolved)
        except (OSError, ValueError):
            return False
        return owner is not None and not _inside_temp(owner.resolve())

    def in_word(self, word: str, cwd: Path) -> bool:
        return any(self.touches(candidate, cwd) for candidate in _candidates(word, cwd))


def _candidates(word: str, cwd: Path) -> Iterator[str]:
    """Every spelling of a path a word may carry.

    The word itself, an option's or assignment's value, a short option's
    attached value, each `:`-separated part of those, each alternative of a
    brace expansion, and any absolute or home-rooted path inside it (inline
    code, a URL-ish value). A relative spelling with no `/` counts only when
    it names something that exists, so a bare argument such as `test` in
    `npm test` run from a project is not read as that project's file.
    """

    values = [word]
    brace = _BRACE_RE.match(word)
    if brace:
        values.extend(
            brace.group(1) + choice + brace.group(3)
            for choice in brace.group(2).split(",")
        )
    for value in list(values):
        if "=" in value:
            values.append(value.split("=", 1)[1])
        if value.startswith("-") and not value.startswith("--") and len(value) > 2:
            values.append(value[2:])
    for value in values:
        for part in {value, *value.split(":")}:
            if not part:
                continue
            if part.startswith("/") or _HOME_PREFIX_RE.match(part):
                yield part
            elif "/" in part or part in {".", ".."} or _exists(cwd / part):
                yield part
        yield from _EMBEDDED_PATH_RE.findall(value)


def _exists(path: Path) -> bool:
    try:
        return path.exists() or path.is_symlink()
    except (OSError, ValueError):
        return False


def _expand_home(raw: str) -> "str | None":
    match = _HOME_PREFIX_RE.match(raw)
    if not match:
        return raw
    home = os.environ.get("HOME") or str(Path.home())
    return home + raw[match.end():] if home else None


def _segments(command: str, cwd: Path, reach: _Reach) -> "list[list[str]] | None":
    """The words of each simple command, once every redirect is judged.

    Outputs must resolve to scratch; inputs only read. A directory change can
    carry into a following segment only through `&&`, which runs that segment
    only if `cd` succeeded. Other shell control flow keeps normal admission.
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
            if segments[-1] and segments[-1][0] in syntax.DIRECTORY_CHANGERS:
                if token != "&&":
                    return None
                changed = _changed_directory(segments[-1], cwd)
                if changed is None or not changed.is_dir():
                    return None
                cwd = changed
            segments.append([])
            index += 1
            continue
        if token in _OUTPUT_REDIRECTS:
            if following not in syntax.DISCARD_TARGETS and not _plain_target(
                following, cwd, reach
            ):
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


def _plain_target(raw: str, cwd: Path, reach: _Reach) -> bool:
    if not raw or _unreadable(raw):
        return False
    expanded = _expand_home(raw)
    return bool(expanded and syntax.scratch_write_target(expanded, cwd)
                and not reach.touches(raw, cwd))


def _unreadable(word: str) -> bool:
    """Text the shell would still compute, beyond the home directory."""

    if word.startswith("~") and not _HOME_PREFIX_RE.match(word):
        return True
    return computed_word(_HOME_VARIABLE_RE.sub("", word))


def _changed_directory(words: list[str], cwd: Path) -> "Path | None":
    """Where a `cd` moves the rest of the line, when the line says where."""

    if words[0] != "cd" or len(words) > 2:
        return None
    if len(words) == 1:
        target = os.environ.get("HOME") or str(Path.home())
    else:
        target = words[1]
        if target == "-" or _unreadable(target):
            return None
        target = _expand_home(target) or ""
    if not target:
        return None
    path = Path(target)
    return path if path.is_absolute() else cwd / path


def _segment_is_scratch(words: list[str], cwd: Path, reach: _Reach) -> bool:
    if any(_unreadable(word) for word in words):
        return False
    program = command_behind_wrappers(words)
    if program is None:
        return False
    if program and Path(program[0]).name == "git":
        if _disposes_of_worktree(program):
            return program[0] == "git" and words == program
        return simple_command_kind(words, cwd) == "read_only"
    if any(Path(word).name in REPOSITORY_PROGRAMS for word in words):
        return False
    if program:
        name = Path(program[0]).name
        if name == "eval" or name in SHELL_STRUCTURE_WORDS:
            return False
        if name in SHELL_PROGRAMS and not _runs_a_script_file(program[1:]):
            return False
        if name in FILE_UTILITIES and not _file_operation_confined(name, program[1:], cwd):
            return False
    if simple_command_kind(words, cwd) == "read_only":
        # Reading a real project changes nothing in it.
        return True
    return not any(reach.in_word(word, cwd) for word in words)


def _runs_a_script_file(arguments: list[str]) -> bool:
    """Whether a shell is handed a script file rather than inline or piped text."""

    for argument in arguments:
        if argument == "--":
            continue
        if argument.startswith("-") and argument != "-":
            if not argument.startswith("--") and set(argument[1:]) & {"c", "s", "i"}:
                return False
            continue
        return argument != "-"
    return False


def _file_operation_confined(name: str, arguments: list[str], cwd: Path) -> bool:
    """Check every write operand of a known file utility, with safe options."""

    operands: list[str] = []
    options_done = False
    for argument in arguments:
        if not options_done and argument == "--":
            options_done = True
            continue
        if not options_done and argument.startswith("-") and argument != "-":
            if not argument.startswith("--") and set(argument[1:]) <= FILE_UTILITIES[name]:
                continue
            return False
        operands.append(argument)
    if name == "chmod":
        if len(operands) < 2:
            return False
        operands = operands[1:]
    if not operands:
        return False
    if name == "cp":
        if len(operands) < 2:
            return False
        operands = operands[-1:]
    if name == "ln":
        if len(operands) != 2:
            return False
        if "-s" not in arguments and not _scratch_path(operands[0], cwd):
            return False
        operands = operands[-1:]
    if name in {"rm", "rmdir", "mv"}:
        return all(_scratch_parent(operand, cwd) for operand in operands)
    return all(_scratch_path(operand, cwd) for operand in operands)


def _scratch_path(raw: str, cwd: Path) -> bool:
    expanded = _expand_home(raw)
    return bool(expanded and not _unreadable(raw)
                and syntax.scratch_write_target(expanded, cwd))


def _scratch_parent(raw: str, cwd: Path) -> bool:
    expanded = _expand_home(raw)
    if (not expanded or _unreadable(raw)
            or set(expanded) & syntax.UNRESOLVED_PATH_CHARS):
        return False
    path = Path(expanded)
    if path.name in {"", ".", ".."}:
        return False
    if raw.endswith("/") and (path if path.is_absolute() else cwd / path).is_symlink():
        return False
    return syntax.scratch_write_target(str(path.parent if path.is_absolute()
                                           else cwd / path.parent), cwd)


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
