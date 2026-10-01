"""Exact read-only grammars for inspection tools outside the core command list.

Owner: command-shape recognition consulted by claude_bash_readonly.simple_command_kind.
Allowed imports: standard library only.
Forbidden: execution, run state, project policy, interpreter-by-name allowances.
Callers/tests: claude_bash_readonly; test_claude_bash_inspection.
Verification: every grammar has an admitted case and a refused neighbour.

Each rule names one program and the exact argument shape under which that
program cannot write. Anything else returns None, and the caller keeps its
fail-closed default. An interpreter is admitted only for a mode that does not
run the program it is given -- a syntax check, a version probe, or the standard
library's JSON pretty-printer in isolated mode reading one file to stdout --
never for a script or a module shadowed by project files.
"""

from __future__ import annotations

from pathlib import Path
import re

# Programs that only report, whatever options they are given: none of them has
# an option that writes a file, runs a program, or signals a process.
INSPECTION_COMMANDS = frozenset({"cmp", "lsof", "md5", "pgrep", "readlink", "shasum"})
PYTHON_NAME_RE = re.compile(r"python(?:\d+(?:\.\d+)*)?")
# `json.tool [infile [outfile]]`: a second operand is a write target.
JSON_TOOL_FLAGS = frozenset({"--sort-keys", "--compact", "--no-ensure-ascii",
                             "--json-lines", "--tab", "--no-indent", "--ensure-ascii"})
# A `tar` listing: one leading mode cluster that contains `t` and only the
# decompression, verbosity and archive-file letters. Every other option --
# `--to-command`, `-I <program>`, `-x`, `-c` -- falls outside the cluster.
TAR_LIST_RE = re.compile(r"-?[vzjJf]*t[vzjJf]*")


def _operands_only(arguments: list[str]) -> bool:
    return all(not argument.startswith("-") for argument in arguments)


def interpreter_probe_kind(command: list[str]) -> str | None:
    """Read-only for a version probe, `node --check`, or `python -I -m json.tool`."""

    if command[0] != Path(command[0]).name:
        return None
    name = command[0]
    is_python = PYTHON_NAME_RE.fullmatch(name) is not None
    if name != "node" and not is_python:
        return None
    arguments = command[1:]
    version_flags = {"--version", "-V"} if is_python else {"--version", "-v"}
    if len(arguments) == 1 and arguments[0] in version_flags:
        return "read_only"
    if name == "node":
        # `--check` parses the file and exits; it never evaluates it.
        if len(arguments) >= 2 and arguments[0] in {"--check", "-c"} and _operands_only(arguments[1:]):
            return "read_only"
        return None
    # -I excludes the project directory and PYTHONPATH from module lookup.
    if arguments[:3] != ["-I", "-m", "json.tool"]:
        return None
    operands = 0
    index = 3
    while index < len(arguments):
        argument = arguments[index]
        flag, equal, value = argument.partition("=")
        if flag == "--indent":
            if not equal:
                index += 1
                value = arguments[index] if index < len(arguments) else ""
            if not value.isdigit():
                return None
        elif argument in JSON_TOOL_FLAGS:
            pass
        elif argument.startswith("-"):
            return None
        else:
            operands += 1
        index += 1
    return "read_only" if operands <= 1 else None


def _ffprobe_metadata_kind(arguments: list[str]) -> str | None:
    """Local metadata to stdout, without output/report or format/protocol options."""
    inputs = 0
    index = 0
    while index < len(arguments):
        word = arguments[index]
        if word in {"-show_format", "-show_streams"}:
            pass
        elif word in {"-v", "-of", "-show_entries"} and index + 1 < len(arguments):
            index += 1
            value = arguments[index]
            if ((word == "-v" and value != "error")
                    or (word == "-of" and value != "json")
                    or (word == "-show_entries" and not re.fullmatch(r"[a-zA-Z0-9_=,:]+", value))):
                return None
        elif word and not word.startswith("-") and (word.startswith("/") or ":" not in word):
            inputs += 1
        else:
            return None
        index += 1
    return "read_only" if inputs == 1 else None


def inspection_command_kind(command: list[str]) -> str | None:
    """The read-only verdict for one exact inspection grammar, or None."""

    if not command:
        return None
    if command[0] != Path(command[0]).name:
        return None
    name = command[0]
    if name in INSPECTION_COMMANDS:
        return "read_only"
    if name == "command":
        arguments = command[1:]
        return "read_only" if (len(arguments) >= 2 and arguments[0] in {"-v", "-V"}
                               and _operands_only(arguments[1:])) else None
    if name == "ffprobe":
        return _ffprobe_metadata_kind(command[1:])
    if name == "unzip":
        # -p streams archive members to stdout; default extraction, combined
        # switches and output-directory options must not inherit this contract.
        arguments = command[1:]
        return "read_only" if (len(arguments) >= 2 and arguments[0] == "-p"
                               and _operands_only(arguments[1:])) else None
    if name == "tar":
        arguments = command[1:]
        if arguments and TAR_LIST_RE.fullmatch(arguments[0]) and _operands_only(arguments[1:]):
            return "read_only"
        return None
    return interpreter_probe_kind(command)
