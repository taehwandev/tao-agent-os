"""Shell syntax for the Claude Bash gate: tokens, operators, and segments.

Split from `claude_bash_readonly.py` so that reading a command line stays
separate from deciding what a command may do. The two failed differently: the
policy half was wrong about which programs write, while this half was wrong
about what the text even said, and an operator it did not model arrived as an
ordinary word. Keeping the lexer, the operator vocabulary, and the segment
splitter together is what lets that vocabulary be audited on its own.
"""

from __future__ import annotations

import os
import re
import shlex
from pathlib import Path


SHELL_PUNCTUATION = frozenset({";", "&", "&&", "|", "||", ">", ">>", "<", "<<"})
REDIRECTIONS = frozenset({">", ">>", "<", "<<"})
# The lexer clusters adjacent metacharacters into one token, so an operator this
# module does not model arrives as an ordinary word rather than as punctuation:
# `>|`, `&>`, `&>>`, `<>` and `>&` all write, and every one of them classified
# as a read while the enumerated set was treated as exhaustive. Recognising the
# shape instead of the spelling is what makes the omission fail closed -- a
# token built only from metacharacters is an operator whether or not it is
# listed above, and an unlisted one is not understood well enough to allow.
OPERATOR_CHARS = frozenset(";&|<>")
# Process and file substitution run a command inside a redirection, so the
# program in the parentheses executes with no token of its own that this module
# would classify. `=(...)` is the zsh spelling and writes a temporary file too.
SUBSTITUTION_MARKERS = ("<(", ">(", "=(")
# Duplication points one stream at another and opens nothing; `-` closes the
# stream. Anything else after `>&` is a filename the shell truncates.
FD_DUPLICATIONS = frozenset({">&", "<&"})
FD_OPERAND_RE = re.compile(r"\d+|-")
# An input redirection feeds a command; it never writes. `>` and `>>` do write,
# except to the discard sink, which is how a probe silences stderr.
INPUT_REDIRECTIONS = frozenset({"<", "<<"})
DISCARD_TARGETS = frozenset({"/dev/null"})
ENV_ASSIGNMENT_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=.*$")
# The one brace form this module resolves, matched positively. Listing the
# operators instead -- strip, default, replace, slice -- was an enumeration
# with the same failure mode as every other one here: `${!REF}` was not on the
# list and passed. Asking whether the braces hold a bare name has a last move,
# because everything that is not a name is something the shell computes.
PLAIN_PARAMETER_RE = re.compile(r"^\$\{[A-Za-z_][A-Za-z0-9_]*\}$")
PARAMETER_BRACE_RE = re.compile(r"\$\{[^}]*\}")
# A substitution stands in for text this module cannot produce. Masking it
# keeps the surrounding command readable; the unresolvable-text rule still
# refuses to claim where such a command writes.
SUBSTITUTION_RE = re.compile(r"\$\(([^()]*)\)|`([^`]*)`")
SUBSTITUTION_PLACEHOLDER = "__tao_substitution__"


def substitution_bodies(command: str) -> list[str]:
    """The commands a substitution will run, in order."""

    return [
        (parenthesised or backticked).strip()
        for parenthesised, backticked in SUBSTITUTION_RE.findall(command)
        if (parenthesised or backticked).strip()
    ]


def mask_substitutions(command: str) -> str:
    """Replace each substitution with a placeholder that names no path."""

    return SUBSTITUTION_RE.sub(SUBSTITUTION_PLACEHOLDER, command)


def bash_command(payload: dict) -> str:
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    command = tool_input.get("command")
    return command if isinstance(command, str) else ""


def bash_invocation(payload: dict, cwd: Path) -> tuple[Path, list[str], bool]:
    """Return effective cwd, simple-command tokens, and syntax confidence."""

    command = bash_command(payload).strip()
    if not command or "\n" in command or "\r" in command:
        return cwd, [], False
    if "$(" in command or "`" in command:
        return cwd, [], False
    # Substitution has to be caught on the raw text: the lexer splits `<(rm -rf
    # build)` into a redirection plus the words inside it, so by token time the
    # command that runs there is indistinguishable from an operand.
    if any(marker in command for marker in SUBSTITUTION_MARKERS):
        return cwd, [], False
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return cwd, [], False
    punctuation = [index for index, token in enumerate(tokens) if token in SHELL_PUNCTUATION]
    if not punctuation:
        return cwd, tokens, True
    # A `cd <dir> && ...` prefix states where the rest of the command runs, and
    # that stays true when the rest is a pipeline. Requiring the whole command
    # to be punctuation-free here meant a session working inside a linked
    # worktree still had every compound command judged against the session cwd,
    # which is the checkout the session was launched from.
    if punctuation[0] == 2 and len(tokens) > 3 and tokens[0] == "cd" and tokens[2] == "&&":
        target = Path(tokens[1]).expanduser()
        if not target.is_absolute():
            target = cwd / target
        try:
            effective_cwd = target.resolve()
        except OSError:
            effective_cwd = target
        rest = tokens[3:]
        return effective_cwd, rest, not any(token in SHELL_PUNCTUATION for token in rest)
    return cwd, tokens, False


def command_segments(tokens: list[str]) -> list[list[str]] | None:
    """Split a compound command into its parts, or None when it can write.

    An output redirection writes a file whatever the commands around it do, so a
    command that contains one never qualifies as read-only. Two forms carry no
    write and are dropped instead: an input redirection only reads, and a
    redirect to the discard sink throws its output away. Refusing those made
    `2>/dev/null` -- the ordinary way to silence a probe's stderr -- enough to
    reclassify a plain `grep` as mutating, so diagnosing this gate inside a
    protected checkout was blocked by the gate itself.
    """
    segments: list[list[str]] = []
    current: list[str] = []
    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in REDIRECTIONS:
            operand = tokens[index + 1] if index + 1 < len(tokens) else None
            if token not in INPUT_REDIRECTIONS and operand not in DISCARD_TARGETS:
                return None
            index += 2
            continue
        if token in SHELL_PUNCTUATION:
            segments.append(current)
            current = []
            index += 1
            continue
        current.append(token)
        index += 1
    segments.append(current)
    return segments if all(segments) else None


def unmodelled_operator(tokens: list[str]) -> bool:
    """Whether any token is an operator this module does not model.

    `>&` and `<&` are the exception, and only when the operand is a file
    descriptor: `2>&1` points one stream at another and opens nothing, which is
    how anyone reads a command's stderr. Refusing it on shape alone blocked
    `cmd 2>&1 | grep`, ordinary inspection, which is the same self-blocking this
    gate has already been repaired for once. Given a filename instead, `>&`
    truncates that file, so the operand is what decides.
    """

    index = 0
    while index < len(tokens):
        token = tokens[index]
        if token in FD_DUPLICATIONS:
            operand = tokens[index + 1] if index + 1 < len(tokens) else None
            if operand is None or not FD_OPERAND_RE.fullmatch(operand):
                return True
            index += 2
            continue
        if token and set(token) <= OPERATOR_CHARS and token not in SHELL_PUNCTUATION:
            return True
        index += 1
    return False


def has_unresolvable_expansion(command: str) -> bool:
    """Whether the shell will build text this module cannot reproduce.

    Enumerating how a path may be spelled is a game with no last move: a
    quoted space, an escaped space, `${VAR%/}`, `$(echo ...)`, and whatever
    comes next each need their own rule, and every one of them was found after
    the previous was fixed. Detecting that the command *will be expanded at
    all* has a last move, because the question stops being which spelling and
    becomes whether this module can claim to know the targets.

    Plain `$VAR` is excluded: expand_path_text resolves it exactly, so it is
    not unresolvable. What remains is substitution and the parameter operators,
    where the value is computed rather than substituted.
    """

    if "$(" in command or "`" in command:
        return True
    return any(
        not PLAIN_PARAMETER_RE.fullmatch(brace)
        for brace in PARAMETER_BRACE_RE.findall(command)
    )


