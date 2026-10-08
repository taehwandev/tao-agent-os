"""Classify trusted user-local context commands and Tao-owned artifact cleanup.

Neither grants ordinary project writes: the only project path this module can
admit is a regular file Tao itself names `*.tao-backup`.
"""

from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import stat

# The suffix both setup writers use (support/setup_config_files.BACKUP_SUFFIX,
# support/project_guidance). Kept literal so the gate imports no setup code.
TAO_BACKUP_SUFFIX = ".tao-backup"
_GLOB_CHARACTERS = frozenset("*?[]{}")


def tao_backup_removal(tokens: list[str], cwd: Path | None) -> bool:
    """Whether a lone `rm [-f] [--] <path>...` only removes Tao backup files.

    Tao writes `<name>.tao-backup` beside a file before its setup rewrites it,
    and nothing else is named that way. Removing one needs no workflow run,
    so this admits it narrowly: only `-f` as an option, no globs, `~` or `..`,
    and every operand must currently be a regular file (not a symlink, not a
    directory) with that suffix. Relative operands need a known cwd. Any other
    operand, option or shell composition leaves the ordinary verdict alone.
    """
    if not tokens or tokens[0] not in {"rm", "/bin/rm"}:
        return False
    operands: list[str] = []
    options_ended = False
    for token in tokens[1:]:
        if not options_ended and token == "--":
            options_ended = True
        elif not options_ended and token.startswith("-"):
            if token != "-f":
                return False
        else:
            operands.append(token)
    return bool(operands) and all(_is_tao_backup_file(operand, cwd) for operand in operands)


def _is_tao_backup_file(operand: str, cwd: Path | None) -> bool:
    if not operand or "\x00" in operand or operand.startswith("~"):
        return False
    if _GLOB_CHARACTERS & set(operand):
        return False
    lexical = Path(operand)
    if ".." in lexical.parts:
        return False
    if not lexical.is_absolute():
        if cwd is None:
            return False
        lexical = cwd / lexical
    name = lexical.name
    if not name.endswith(TAO_BACKUP_SUFFIX) or name == TAO_BACKUP_SUFFIX:
        return False
    try:
        # The parent may be reached through a symlinked directory; the entry
        # rm unlinks is still this name inside the resolved directory.
        entry = lexical.parent.resolve(strict=True) / name
        return stat.S_ISREG(os.lstat(entry).st_mode)
    except (OSError, RuntimeError, ValueError):
        return False


def spill_label_kind(arguments: list[str]) -> str | None:
    """The installed helper's label-only mode writes local context, not a project."""
    expected = Path.home() / "Library/Application Support/Spill/adapters/setup/spill-token-metering-setup.mjs"
    if not arguments:
        return None
    try:
        if not expected.is_file() or Path(arguments[0]).expanduser().resolve() != expected.resolve():
            return None
    except (OSError, RuntimeError):
        return None
    values: dict[str, str] = {}
    index = 1
    while index < len(arguments):
        flag = arguments[index]
        if flag in values:
            return None
        if flag == "--if-absent":
            values[flag] = "true"
        elif flag in {"--label", "--task-type", "--stage"} and index + 1 < len(arguments):
            index += 1
            values[flag] = arguments[index]
        else:
            return None
        index += 1
    if values.get("--label") not in {"codex", "claude", "antigravity", "agy", "openai"}:
        return None
    if not all(re.fullmatch(r"[a-z][a-z0-9_]{1,40}", values.get(key, ""))
               for key in ("--task-type", "--stage")):
        return None
    return "runtime_control"


def guarded_label_tokens(command: str) -> list[str] | None:
    """Recognize only the installed label helper's existing-file guard.

    Keep quote information: a single-quoted $HOME is literal project text,
    while this double-quoted prefix denotes the runtime's home directory.
    """
    try:
        lexer = shlex.shlex(command, posix=False, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        words = list(lexer)
        if (len(words) < 12 or words[:3] != ["if", "[", "-f"]
                or words[4:8] != ["]", ";", "then", "node"] or words[-2:] != [";", "fi"]
                or words[3] != words[8]):
            return None
        raw = words[8]
        path = shlex.split(raw)[0]
        for prefix in ("$HOME/", "${HOME}/"):
            if raw == '"' + path + '"' and path.startswith(prefix):
                path = str(Path.home()) + "/" + path[len(prefix):]
                break
        if not Path(path).is_absolute() or any(marker in path for marker in ("$", "`", "\\")):
            return None
        arguments = [path, *shlex.split(" ".join(words[9:-2]))]
    except (ValueError, IndexError):
        return None
    return ["node", *arguments] if spill_label_kind(arguments) is not None else None


def local_context_kind(alias: str, arguments: list[str]) -> str | None:
    """Called only after the executable's canonical identity has been checked.

    Storage implementations own input validation. Unknown options and surplus
    operands must not inherit the lifecycle exemption of a known operation.
    """
    if alias == "project-memory":
        operations = {
            "capture": ({"--source", "--review-on", "--scope", "--replaces"}, set(), 0),
            "retire": (set(), set(), 1),
            "approve": ({"--digest"}, set(), 1),
            "recall": ({"--scope"}, set(), 0),
            "history": (set(), set(), 1),
        }
    elif alias == "agent-mailbox":
        operations = {
            "send": ({"--rules", "--evidence", "--to", "--sender", "--kind", "--ttl-seconds"}, {"--json"}, 0),
            "receive": ({"--runtime", "--limit"}, {"--json"}, 0),
            "status": ({"--runtime"}, {"--json"}, 0),
        }
    elif alias == "mailbox-hook":
        operations = {
            "authorize-task": ({"--runtime", "--evidence", "--message-id"}, set(), 0),
            "pause-tasks": ({"--runtime"}, set(), 0),
            "complete-task": ({"--runtime", "--message-id"}, set(), 0),
        }
    else:
        return None
    operation, operands, index = "", 0, 0
    while index < len(arguments):
        word = arguments[index]
        flag, equal, value = word.partition("=")
        valued, switches, _ = operations.get(operation, (set(), set(), 0))
        if flag == "--project" or flag in valued:
            if not equal:
                index += 1
                if index >= len(arguments):
                    return None
                value = arguments[index]
            if not value or value.startswith("--"):
                return None
        elif word in switches:
            pass
        elif not operation and word in operations:
            operation = word
        elif operation and not word.startswith("-"):
            operands += 1
        else:
            return None
        index += 1
    if not operation or operands != operations[operation][2]:
        return None
    return "read_only" if operation in {"recall", "history", "status"} else "runtime_control"
