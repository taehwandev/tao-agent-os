"""Raw command-line segments for the pre-tool gate's publication reading.

Owner: splitting raw shell text into simple commands before unquoting, and
finding the substitutions that would run, for callers that must say which
program each segment runs. The shell vocabulary it reads with -- operators,
substitution markers, wrappers -- is owned by claude_bash_syntax.
Allowed imports: the standard library and claude_bash_syntax.
Forbidden imports: any gate, policy or run-evidence module.
Callers/tests: claude_pretool_publication, claude_pretool_finished_admission;
tests/test_claude_shell_parser_parity.py.
Verification: that module, then tests/test_claude_pretool_gate.py.
"""

from __future__ import annotations

import re
import shlex
from typing import Callable

from claude_bash_syntax import (
    OPERATOR_CHARS,
    RUNNING_SUBSTITUTION_MARKERS,
    SUBSTITUTED_WORD,
    ZSH_FILE_SUBSTITUTION,
)

# Only a duplication between the standard output streams is dropped, never an
# arbitrary descriptor that may name an already-open file.
_STANDARD_STREAM_DUPLICATION_RE = re.compile(r"[12]?>&[12](?=$|[ \t\n;&|])")


def _word_start(command: str, index: int) -> bool:
    return index == 0 or command[index - 1].isspace() or command[index - 1] in OPERATOR_CHARS


def substitution_end(command: str, index: int) -> "int | None":
    """Index of the `)` closing the `$(` whose body starts at `index`."""

    depth = 1
    quote = ""
    while index < len(command):
        character = command[index]
        if character == "\\" and quote != "'":
            index += 2
            continue
        if quote:
            if character == quote:
                quote = ""
        elif character in "'\"":
            quote = character
        elif character == "(":
            depth += 1
        elif character == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def read_substitutions(
    command: str, judge: "Callable[[str], str]", decisive: str
) -> "tuple[str, str] | None":
    """Judge each `$(...)` body and put one inert word in its place.

    Returns the rewritten line and the first non-empty verdict, or the
    original line and `decisive` as soon as a body is judged that way. An
    arithmetic `$((...))` runs nothing unless it nests a substitution.
    Backticks and process substitution are left for `raw_command_segments`
    to refuse. None means an unterminated or unreadable substitution.
    """

    pieces: list[str] = []
    verdict = ""
    quote = ""
    index = 0
    while index < len(command):
        character = command[index]
        if quote == "'":
            pieces.append(character)
            if character == "'":
                quote = ""
            index += 1
            continue
        if character == "\\":
            pieces.append(command[index:index + 2])
            index += 2
            continue
        if not quote and character == "#" and _word_start(command, index):
            newline = command.find("\n", index)
            end = len(command) if newline < 0 else newline
            pieces.append(command[index:end])
            index = end
            continue
        if command.startswith("$(", index):
            end = substitution_end(command, index + 2)
            if end is None:
                return None
            body = command[index + 2:end]
            if body.startswith("(") and body.endswith(")"):
                if "$(" in body or "`" in body:
                    return None
                pieces.append("0")
            else:
                found = judge(body)
                if found == decisive:
                    return command, decisive
                verdict = verdict or found
                pieces.append(SUBSTITUTED_WORD)
            index = end + 1
            continue
        if character == '"':
            quote = "" if quote else '"'
        elif character == "'" and not quote:
            quote = "'"
        pieces.append(character)
        index += 1
    return "".join(pieces), verdict


def substitution_runs(command: str) -> bool:
    """Whether a substitution marker sits where the shell would run it.

    Single quotes and a comment hide it; double quotes do not, because
    `"$(git push)"` runs.
    """

    quote = ""
    index = 0
    while index < len(command):
        character = command[index]
        if quote:
            if character == quote:
                quote = ""
            elif quote == '"':
                if character == "\\":
                    index += 1
                elif command.startswith(RUNNING_SUBSTITUTION_MARKERS, index):
                    return True
            index += 1
            continue
        if character in "'\"":
            quote = character
            index += 1
            continue
        if character == "\\":
            index += 2
            continue
        # `;#` opens a comment as surely as ` #` does.
        if character == "#" and _word_start(command, index):
            return False
        if command.startswith(RUNNING_SUBSTITUTION_MARKERS, index) or (
            command.startswith(ZSH_FILE_SUBSTITUTION, index) and _word_start(command, index)
        ):
            return True
        index += 1
    return False


def _raw_command_parts(command: str, reject_redirections: bool) -> "list[str] | None":
    """Split operators before unquoting so literal punctuation stays data."""

    parts: list[str] = []
    current: list[str] = []
    quote = ""
    word_start = True
    index = 0
    while index < len(command):
        char = command[index]
        if not quote and word_start:
            # Only duplicate the standard output streams, never an arbitrary
            # descriptor that may name an already-open file.
            descriptor = _STANDARD_STREAM_DUPLICATION_RE.match(command[index:])
            if descriptor:
                index += descriptor.end()
                continue
            if command.startswith(ZSH_FILE_SUBSTITUTION, index):
                return None
        if char == "\\" and quote != "'":
            if index + 1 >= len(command):
                return None
            following = command[index + 1]
            if following != "\n":
                current.extend((char, following))
                word_start = False
            index += 2
            continue
        if quote != "'" and command.startswith(RUNNING_SUBSTITUTION_MARKERS, index):
            return None
        if quote:
            current.append(char)
            if char == quote:
                quote = ""
        elif char in "\"'":
            quote = char
            current.append(char)
            word_start = False
        elif char == "#" and word_start:
            # A comment ends at the newline; later commands still need checks.
            newline = command.find("\n", index)
            index = len(command) if newline < 0 else newline
            continue
        elif char == "\n" or char in OPERATOR_CHARS:
            if reject_redirections and char in "<>":
                return None
            if current:
                parts.append("".join(current))
                current = []
            word_start = True
        else:
            current.append(char)
            word_start = char in " \t"
        index += 1
    if quote:
        return None
    if current:
        parts.append("".join(current))
    return parts


def raw_command_segments(
    command: str, *, reject_redirections: bool = False
) -> "list[list[str]] | None":
    """Simple commands of a raw line, or None for hidden substitutions or bad syntax."""

    parts = _raw_command_parts(command, reject_redirections)
    if parts is None:
        return None
    segments: list[list[str]] = []
    for part in parts:
        if substitution_runs(part):
            return None
        try:
            tokens = shlex.split(part)
        except ValueError:
            return None
        if tokens:
            segments.append(tokens)
    return segments
