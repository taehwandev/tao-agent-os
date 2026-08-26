"""Which paths a Bash command names, however it spells them.

Split from `claude_bash_syntax.py` because reading a command's structure and
reading its targets failed for different reasons: the structure half missed an
operator it did not model, while this half missed a spelling -- a quoted space,
an escaped space, a value after `=`, a runtime variable, quotes used to join
fragments. Every one of those arrived after the previous was closed, so the
spelling vocabulary is what needs to be auditable on its own.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path

from claude_bash_syntax import (
    FD_DUPLICATIONS,
    OPERATOR_CHARS,
    REDIRECTIONS,
    SHELL_PUNCTUATION,
)


# Absolute paths anywhere inside a token, not only at its start: after an
# option's `=`, after an operand assignment's `=`, or embedded in a quoted
# script body an interpreter receives as one word.
# Two forms, quoted first: inside a script body a path containing spaces is
# still delimited by its quotes, and stopping at the first space turned
# `"/root/protected space/f"` into a directory that does not exist.
EMBEDDED_PATH_RE = re.compile(
    r"""["']\s*(~?/[^"']*)["']|(~?/(?:\\.|[^\s'"=\\])*)"""
)
QUOTE_RE = re.compile(r"[\"']")


def unescape_path(text: str) -> str:
    """Drop the backslashes a shell uses to carry a literal character.

    `protected\\ space` and `"protected space"` name the same directory, and
    only the quoted spelling was recognised, so the escaped one reached a
    protected checkout untouched. The shell removes the backslash before the
    program ever sees the path, so this reads what the program will.
    """

    return re.sub(r"\\(.)", r"\1", text)


def expand_path_text(text: str) -> str:
    """Substitute environment variables so a named target resolves to a path.

    `touch $CLAUDE_PROJECT_DIR/f` names the protected checkout as plainly as
    the literal path does, and the shell it is handed to will expand it; the
    gate read the unexpanded text, found no path, and allowed the write. The
    same environment the command will run with is the one to read it through.

    A variable this process cannot see stays literal, so it still yields no
    path. That residual case is narrower than before rather than closed, and
    only shrinks as more of the command's environment is present here.
    """

    if "$" not in text:
        return text
    return os.path.expandvars(text)


def raw_path_arguments(command: str) -> list[Path]:
    """Absolute paths named anywhere in a command this module could not parse.

    Refusing to tokenise is how a heredoc, a substitution or an unbalanced
    quote is handled, and it leaves no tokens for the caller to judge. That is
    correct for deciding what the command *does*, and wrong for deciding *where*
    it does it: `cd <protected> && python3 - <<'E'` parsed to nothing, so the
    directory it names was invisible and the command ran unexamined. Reading
    the text for paths does not require understanding the syntax, and a command
    that cannot be understood is exactly the one that should be judged against
    every checkout it mentions.
    """

    paths: list[Path] = []
    expanded = expand_path_text(command)
    for text in (expanded, QUOTE_RE.sub("", expanded)):
        for quoted, bare in EMBEDDED_PATH_RE.findall(text):
            candidate = quoted or bare
            if candidate and candidate not in {"/", "~/"}:
                path = Path(unescape_path(candidate)).expanduser()
                if path not in paths:
                    paths.append(path)
    return paths


# `cp` is the one shape where naming a protected path is the whole point of a
# permitted action: seeding a linked worktree with the gitignored local files
# that only the main checkout holds. Judged by paths alone the copy reads as a
# write into the checkout it only reads from, so the gate refused the exact
# move its own denial message asks for, and no other source existed -- an
# ignored file is not in the object store, so no worktree could supply it.
#
# Only the plain form is modelled. `-t` and `--target-directory` put the
# destination first, so a flag outside this set leaves the command judged by
# every path it names, which is the stricter reading.
COPY_SAFE_SHORT_FLAG_RE = re.compile(r"-[aLPRfnprv]+")
COPY_SEGMENT_SEPARATORS = SHELL_PUNCTUATION - REDIRECTIONS
TRUSTED_COPY_LOCATIONS = (Path("/bin/cp"), Path("/usr/bin/cp"))


def copy_source_token_indices(tokens: list[str]) -> frozenset[int]:
    """Original token positions a trusted plain `cp` only reads from.

    Positions, rather than values, are the security boundary: a later command
    may spell a write target exactly like an earlier copy source. Segments keep
    their original positions, and a segment containing any redirection or an
    operator outside this narrow model receives no source exemption.
    """

    sources: set[int] = set()
    start = 0
    for index, token in enumerate([*tokens, ";"]):
        if token not in COPY_SEGMENT_SEPARATORS:
            continue
        if start < index:
            sources.update(_copy_segment_source_indices(tokens[start:index], start))
        start = index + 1
    return frozenset(sources)


def _copy_segment_source_indices(tokens: list[str], offset: int) -> list[int]:
    """Read-only operands of one simple `cp`, or nothing when unsure.

    The destination is the last operand, so every earlier operand is a source.
    Returning an empty list is the safe answer: the caller then keeps judging
    the command by all of its paths.
    """

    if not tokens or not _trusted_copy_executable(tokens[0]):
        return []
    rest = tokens[1:]
    if any(_copy_segment_token_is_uncertain(token) for token in rest):
        return []
    operands: list[int] = []
    separator_seen = False
    for relative_index, token in enumerate(rest, start=1):
        if not separator_seen and token == "--":
            separator_seen = True
            continue
        if not separator_seen and token.startswith("-"):
            if COPY_SAFE_SHORT_FLAG_RE.fullmatch(token) is None:
                return []
            continue
        operands.append(offset + relative_index)
    return operands[:-1] if len(operands) >= 2 else []


def _copy_segment_token_is_uncertain(token: str) -> bool:
    if token in REDIRECTIONS or token in FD_DUPLICATIONS:
        return True
    return bool(token) and set(token) <= OPERATOR_CHARS


def _trusted_copy_executable(token: str) -> bool:
    """Whether the shell token selects the host's trusted system `cp`.

    A bare name is resolved through the hook's PATH, matching what its child
    shell will execute. A path spelling must be absolute. Both forms must
    resolve to a regular system copy executable; a basename match such as
    `/tmp/cp` is never enough.
    """

    if token == "cp":
        candidate = shutil.which(token)
        if not candidate:
            return False
        selected = Path(candidate)
    else:
        selected = Path(token)
        if not selected.is_absolute():
            return False
    try:
        resolved = selected.resolve(strict=True)
        mode = resolved.stat().st_mode
        trusted = {
            candidate.resolve(strict=True)
            for candidate in TRUSTED_COPY_LOCATIONS
            if candidate.exists()
        }
    except (OSError, ValueError):
        return False
    return stat.S_ISREG(mode) and resolved in trusted


def path_arguments(tokens: list[str]) -> list[Path]:
    """Every path a command names, however it spells it.

    Reading only tokens that begin with a slash left three spellings invisible,
    and each of them wrote into a protected checkout: an option carries its
    target after `=` (`git diff --output=/x`), so does an operand assignment
    (`dd of=/x`), and an interpreter takes a whole script as one quoted token
    (`sh -c 'touch /x'`) where the path is a substring rather than an argument.
    Scanning inside each token covers all three, because what matters is that
    the path is named at all, not which argv slot it occupies.

    Relative paths are returned unresolved for the caller to join to the
    directory the command runs in; a relative path is how the same target is
    reached without ever writing a slash first.

    A target built at runtime, `$TARGET/file`, is still invisible: this reads
    the text the shell was given, not what it expands to. That limit is stated
    rather than papered over, since the same token yields a path only when the
    variable is not what carries it.
    """

    paths: list[Path] = []
    for token in tokens:
        if not token or token in SHELL_PUNCTUATION:
            continue
        remainder = token.split("=", 1)[1] if "=" in token else token
        candidate = expand_path_text(remainder)
        if candidate.startswith(("/", "~/")):
            # The whole token, not a pattern match: quoting is what carries a
            # path containing spaces, and matching up to the first space cut
            # `"<root>/protected space/f"` down to a directory that does not
            # exist, so the protected checkout was never found.
            paths.append(Path(candidate).expanduser())
            continue
        # Two passes over the same text. The first keeps quotes, because a
        # quoted path is how a space survives; the second removes them, because
        # adjacent quotes are how a path is assembled -- `/main/pro"j"/f` is one
        # path to the shell and two fragments to any pattern that treats a
        # quote as a boundary.
        expanded = expand_path_text(token)
        for text in (expanded, QUOTE_RE.sub("", expanded)):
            for quoted, bare in EMBEDDED_PATH_RE.findall(text):
                embedded = quoted or bare
                if embedded and embedded not in {"/", "~/"}:
                    candidate_path = Path(unescape_path(embedded)).expanduser()
                    if candidate_path not in paths:
                        paths.append(candidate_path)
        if candidate and not candidate.startswith("-"):
            # A bare word can still be a relative target; the caller decides
            # whether the directory it belongs to is protected.
            paths.append(Path(candidate))
    return paths
